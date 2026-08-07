from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Engine

from .chat import (
    STARTER_TOPICS,
    ChatOutputError,
    assistant_content,
    chat_messages,
    correction_payload,
    generate_chat_turn,
    suppress_follow_up,
    topic_for,
)
from .companion import build_companion_messages
from .config import ROOT_DIR, get_settings
from .db import apply_schema, make_engine
from .furigana import ruby_segments
from .llm import LLMService
from .omni import relay_voice_teacher
from .repository import Repository
from .storage import ObjectStorage
from .voice import validate_video_voice_clip, voice_separation_available


class MaterialCreate(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    text: str | None = Field(default=None, max_length=100_000)
    url: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def has_exactly_one_source(self) -> MaterialCreate:
        if bool(self.text and self.text.strip()) == bool(self.url and self.url.strip()):
            raise ValueError("请粘贴文本或输入一个链接，二选一。")
        return self


class CompanionRequest(BaseModel):
    material_id: int
    segment_id: int | None = None
    question: str = Field(min_length=1, max_length=4_000)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4_000)

    @field_validator("session_id", "message")
    @classmethod
    def legacy_chat_fields_are_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("会话与消息不能为空。")
        return value


class ChatSessionCreate(BaseModel):
    topic: str | None = Field(default=None, max_length=160)
    starter_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def has_topic(self) -> ChatSessionCreate:
        if bool((self.topic or "").strip()) == bool((self.starter_id or "").strip()):
            raise ValueError("请选择精选主题或输入自定义主题，二选一。")
        return self


class ChatMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)

    @field_validator("message")
    @classmethod
    def message_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息不能为空。")
        return value


class VideoLinkCreate(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    url: str = Field(min_length=1, max_length=2_000)


class PlaybackStateUpdate(BaseModel):
    position_ms: int = Field(ge=0, le=2_147_483_647)


def title_for_text(value: str) -> str:
    first_line = next((line.strip() for line in value.splitlines() if line.strip()), "未命名材料")
    return f"{first_line[:36]}{'…' if len(first_line) > 36 else ''}"


def title_for_url(value: str) -> str:
    return urlparse(value).netloc or "网页材料"


_MATERIAL_JOB_PRESENTATION: dict[str, tuple[str, int, int]] = {
    "fetch": ("正在提取网页内容", 12, 3),
    "vision": ("正在识别照片文字", 18, 3),
    "tts": ("正在生成朗读音频", 58, 5),
    "download_video": ("正在下载视频", 15, 10),
    "transcode": ("正在处理视频", 38, 10),
    "upload_video": ("正在上传媒体", 62, 8),
    "asr_video": ("正在转录字幕", 82, 5),
    "translate_video": ("正在翻译字幕", 95, 2),
}

_MATERIAL_FAILURE_TITLES = {
    "fetch": "网页导入失败",
    "vision": "照片识别失败",
    "tts": "朗读生成失败",
    "download_video": "视频下载失败",
    "transcode": "视频处理失败",
    "upload_video": "媒体上传失败",
    "asr_video": "转录失败",
    "translate_video": "字幕翻译失败",
}


def _error_summary(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("timeout", "timed out", "connection", "network", "requesterror", "http")):
        return "网络连接中断"
    if any(token in lowered for token in ("key", "unauthorized", "forbidden", "401", "403")):
        return "服务配置或授权无效"
    if any(token in lowered for token in ("disk", "space", "磁盘", "空间不足")):
        return "本机存储空间不足"
    if any(token in lowered for token in ("format", "codec", "ffmpeg", "格式")):
        return "文件格式或媒体处理异常"
    return "后台处理未能完成"


def _job_eta_minutes(kind: str, payload: dict, updated_at: datetime | None, default_minutes: int) -> int:
    estimate = default_minutes
    if kind == "tts":
        text_length = len(str(payload.get("text", "")))
        estimate = max(default_minutes, round(text_length / 16 / 60) + 2)
    if updated_at is not None:
        reference = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=UTC)
        elapsed = max(0, int((datetime.now(UTC) - reference).total_seconds() / 60))
        estimate = max(1, estimate - elapsed)
    return estimate


def serialise_material(material: dict) -> dict:
    settings = get_settings()
    audio_key = material.pop("audio_oss_key", None)
    video_key = material.pop("video_oss_key", None)
    thumbnail_path = material.pop("thumbnail_local_path", None)
    job_id = material.pop("current_job_id", None)
    job_kind = str(material.pop("current_job_kind", "") or "")
    job_status = str(material.pop("current_job_status", "") or "")
    job_error = str(material.pop("current_job_error_message", "") or "")
    job_payload = dict(material.pop("current_job_payload", None) or {})
    job_updated_at = material.pop("current_job_updated_at", None)
    material["audio_url"] = (
        f"{settings.oss_public_base_url.rstrip('/')}/{audio_key}" if audio_key and settings.oss_public_base_url else None
    )
    material["video_url"] = (
        f"{settings.oss_public_base_url.rstrip('/')}/{video_key}"
        if video_key and settings.oss_public_base_url
        else None
    )
    material["thumbnail_path"] = f"/materials/{material['id']}/thumbnail" if thumbnail_path else None
    material["job_id"] = int(job_id) if job_id is not None else None
    material["progress_percent"] = None
    material["progress_label"] = None
    material["eta_minutes"] = None
    material["retryable"] = False
    material["failure_title"] = None
    material["failure_summary"] = None

    if material.get("status") in {"pending", "processing"}:
        label, percent, eta = _MATERIAL_JOB_PRESENTATION.get(job_kind, ("正在准备素材", 8, 3))
        if job_status == "pending":
            percent = max(3, percent - 6)
        material["progress_percent"] = percent
        material["progress_label"] = label
        material["eta_minutes"] = _job_eta_minutes(job_kind, job_payload, job_updated_at, eta)
    elif material.get("status") == "downloaded":
        material["progress_percent"] = 45
        material["progress_label"] = "视频已准备，等待开始转录"
    elif material.get("status") == "failed":
        raw_error = str(material.get("error_message") or job_error or "后台处理未能完成")
        material["failure_title"] = _MATERIAL_FAILURE_TITLES.get(job_kind, "素材处理失败")
        material["failure_summary"] = _error_summary(raw_error)
        material["retryable"] = job_status == "failed" and bool(job_id)
    return material


_engine: Engine | None = None
_repository: Repository | None = None
_llm_service: LLMService | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _engine, _repository, _llm_service
    engine = make_engine()
    llm = LLMService(get_settings())
    try:
        apply_schema(engine)
        _engine = engine
        _repository = Repository(engine)
        _llm_service = llm
        yield
    finally:
        llm.close()
        engine.dispose()
        if _engine is engine:
            _engine = None
            _repository = None
        if _llm_service is llm:
            _llm_service = None


app = FastAPI(title="Harvest", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT_DIR / "backend" / "app" / "static"), name="static")
templates = Jinja2Templates(directory=ROOT_DIR / "backend" / "app" / "templates")

templates.env.filters["datetime_local"] = lambda value: value.strftime("%Y-%m-%d %H:%M") if value else "—"
_STATUS_LABELS = {
    "pending": "待处理",
    "processing": "处理中",
    "downloaded": "待转录",
    "ready": "已就绪",
    "failed": "失败",
}
_JOB_STATUS_LABELS = {"pending": "待处理", "running": "执行中", "done": "完成", "failed": "失败"}
_STATUS_TAGS = {
    "pending": "is-warning is-light",
    "processing": "is-info is-light",
    "downloaded": "is-warning is-light",
    "ready": "is-success is-light",
    "failed": "is-danger is-light",
}
_JOB_STATUS_TAGS = {
    "pending": "is-warning is-light",
    "running": "is-info is-light",
    "done": "is-success is-light",
    "failed": "is-danger is-light",
}
templates.env.filters["status_label"] = lambda s: _STATUS_LABELS.get(s, s)
templates.env.filters["status_tag"] = lambda s: _STATUS_TAGS.get(s, "is-light")
templates.env.filters["job_status_label"] = lambda s: _JOB_STATUS_LABELS.get(s, s)
templates.env.filters["job_status_tag"] = lambda s: _JOB_STATUS_TAGS.get(s, "is-light")
templates.env.filters["kind_label"] = lambda k: {"reading": "阅读", "video": "视频"}.get(k, k)

_JOB_KINDS = (
    "fetch", "tts", "asr", "vision", "download_video", "transcode",
    "upload_video", "asr_video", "translate_video", "shadowing",
    "voice_enrollment", "voice_enrollment_video",
)


def page_context(active: str, **extra: object) -> dict[str, object]:
    return {"active": active, **extra}


def repository() -> Repository:
    if _repository is None:
        raise RuntimeError("应用数据库尚未初始化。")
    return _repository


def llm_service() -> LLMService:
    if _llm_service is None:
        raise RuntimeError("应用文本模型服务尚未初始化。")
    return _llm_service


_SETTINGS_KEYS = (
    "DATABASE_URL", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL", "DASHSCOPE_TTS_MODEL",
    "DASHSCOPE_TTS_VOICE", "DASHSCOPE_ASR_MODEL", "DASHSCOPE_CHAT_BASE_URL",
    "DASHSCOPE_CHAT_MODEL", "DASHSCOPE_OMNI_MODEL", "DASHSCOPE_VL_MODEL",
    "DASHSCOPE_OMNI_WS_URL", "DASHSCOPE_OMNI_VOICE", "DASHSCOPE_OMNI_INSTRUCTIONS",
    "LLM_PROVIDER", "LLM_FALLBACK_ON_ERROR",
    "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL", "OSS_ENDPOINT", "OSS_BUCKET", "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET",
    "OSS_PUBLIC_BASE_URL", "OSS_TEMPORARY_RETENTION_DAYS", "OSS_SHADOWING_RETENTION_DAYS",
    "OSS_UPLOAD_TIMEOUT_SECONDS", "OSS_UPLOAD_MAX_ATTEMPTS",
    "TAILSCALE_HOSTNAME", "MAX_VIDEO_UPLOAD_BYTES", "MAX_PHOTO_UPLOAD_BYTES",
    "MAX_AUDIO_UPLOAD_BYTES", "MIN_FREE_DISK_BYTES", "VIDEO_DOWNLOAD_MAX_HEIGHT",
    "VIDEO_DOWNLOAD_MAX_FPS", "VIDEO_TRANSCODE_MAX_THREADS",
)
_SECRET_KEYS = {"DATABASE_URL", "DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY", "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET"}


def _update_env(values: dict[str, str], clear_keys: set[str] | None = None) -> None:
    env_path = ROOT_DIR / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    clear_keys = (clear_keys or set()) & _SECRET_KEYS
    remaining = {key: value for key, value in values.items() if key in _SETTINGS_KEYS and value.strip()}
    updated: list[str] = []
    for line in lines:
        key = line.partition("=")[0]
        if key in clear_keys:
            updated.append(f"{key}=")
        elif key in remaining:
            updated.append(f"{key}={shlex.quote(remaining.pop(key))}")
        else:
            updated.append(line)
    existing_keys = {line.partition("=")[0] for line in lines}
    updated.extend(f"{key}=" for key in clear_keys - existing_keys)
    updated.extend(f"{key}={shlex.quote(value)}" for key, value in remaining.items())
    env_path.write_text("\n".join(updated) + "\n")
    os.chmod(env_path, 0o600)
    get_settings.cache_clear()


def _reject_duplicate_source(url: str) -> None:
    """Stop the same link becoming a second material (§5.2.1).

    Re-importing a link that failed is almost always meant as a retry, so point
    at the retry action instead of silently paying for another download.
    """
    existing = repository().find_material_by_source_url(url)
    if existing is None:
        return
    title = existing["title"] or "未命名素材"
    if existing["status"] == "failed":
        detail = f"这个链接已经导入过了：「{title}」（素材 #{existing['id']}，之前处理失败）。请在素材库里点重试，不要重新导入。"
    else:
        detail = f"这个链接已经导入过了：「{title}」（素材 #{existing['id']}）。直接打开它就行。"
    raise HTTPException(status_code=409, detail=detail)


def create_material(payload: MaterialCreate) -> tuple[int, int]:
    repo = repository()
    if payload.text and payload.text.strip():
        source_text = payload.text.strip()
        return repo.create_material_with_job(
            title=(payload.title or "").strip() or title_for_text(source_text),
            source_type="paste",
            source_ref=None,
            job_kind="tts",
            payload={"text": source_text},
        )
    assert payload.url
    source_url = payload.url.strip()
    _reject_duplicate_source(source_url)
    title_provided = bool((payload.title or "").strip())
    return repo.create_material_with_job(
        title=(payload.title or "").strip() or title_for_url(source_url),
        source_type="url",
        source_ref=source_url,
        job_kind="fetch",
        payload={"url": source_url, "title_provided": title_provided},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: int | None = None, voice_job: int | None = None) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "settings.html", settings_context(saved=saved, voice_job=voice_job)
    )


def settings_context(**messages: object) -> dict[str, object]:
    settings = get_settings()
    secret_status = {key: bool(getattr(settings, key.lower(), None)) for key in _SECRET_KEYS}
    values = {key: getattr(settings, key.lower(), "") for key in _SETTINGS_KEYS if key not in _SECRET_KEYS}
    profiles = _repository.voice_profiles() if _repository is not None else []
    return {
        "active": "settings",
        "status": secret_status,
        "values": values,
        "voice_profiles": profiles,
        "voice_separation_ready": voice_separation_available(),
        **messages,
    }


@app.post("/settings", response_class=HTMLResponse)
async def save_settings(request: Request) -> RedirectResponse:
    form = await request.form()
    clear_keys = {key for key in _SECRET_KEYS if str(form.get(f"CLEAR_{key}", "")).lower() in {"1", "true", "on"}}
    _update_env({key: str(form.get(key, "")) for key in _SETTINGS_KEYS}, clear_keys)
    return RedirectResponse(url="/settings?saved=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/settings/oss-lifecycle", response_class=HTMLResponse)
def apply_oss_lifecycle(request: Request) -> HTMLResponse:
    try:
        rules = ObjectStorage(get_settings()).configure_lifecycle()
    except Exception as error:
        return templates.TemplateResponse(
            request,
            "settings.html",
            settings_context(lifecycle_error=str(error)),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return templates.TemplateResponse(
        request,
        "settings.html",
        settings_context(lifecycle_rules=rules),
    )


@app.post("/videos", status_code=status.HTTP_202_ACCEPTED)
async def post_video(title: Annotated[str | None, Form()] = None, video: UploadFile = File()) -> dict[str, int | str]:
    if not video.filename:
        raise HTTPException(status_code=422, detail="请选择一个视频文件。")
    if not (video.content_type or "").startswith("video/"):
        raise HTTPException(status_code=415, detail="只接受视频文件。")
    suffix = Path(video.filename).suffix.lower() or ".mp4"
    if suffix not in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
        raise HTTPException(status_code=415, detail="暂不支持这种视频格式。")
    settings = get_settings()
    video_dir = settings.data_dir / "video" / "uploads"
    video_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(video_dir).free < settings.min_free_disk_bytes:
        raise HTTPException(status_code=507, detail="本机磁盘空间不足，暂不能接收视频。")
    destination = video_dir / f"upload-{int(time.time() * 1000)}{suffix}"
    await save_upload_stream(
        video, destination, settings.max_video_upload_bytes, settings.min_free_disk_bytes, "视频"
    )
    material_id, job_id = repository().create_material_with_job(
        kind="video", title=(title or "").strip() or Path(video.filename).stem,
        source_type="file", source_ref=video.filename, job_kind="transcode", payload={"source_path": str(destination)},
    )
    return {"material_id": material_id, "job_id": job_id, "status": "pending"}


def create_video_link(payload: VideoLinkCreate) -> tuple[int, int]:
    url = payload.url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="请输入完整的 http 或 https 视频链接。")
    _reject_duplicate_source(url)
    title_provided = bool((payload.title or "").strip())
    return repository().create_material_with_job(
        kind="video",
        title=(payload.title or "").strip() or parsed.netloc,
        source_type="url",
        source_ref=url,
        job_kind="download_video",
        payload={"url": url, "title_provided": title_provided},
    )


@app.post("/videos/link", status_code=status.HTTP_202_ACCEPTED)
def post_video_link(payload: VideoLinkCreate) -> dict[str, int | str]:
    material_id, job_id = create_video_link(payload)
    return {"material_id": material_id, "job_id": job_id, "status": "pending"}


@app.post("/photos", status_code=status.HTTP_202_ACCEPTED)
async def post_photo(title: Annotated[str | None, Form()] = None, photo: UploadFile = File()) -> dict[str, int | str]:
    if not photo.filename:
        raise HTTPException(status_code=422, detail="请选择一张照片。")
    if (photo.content_type or "") not in {"image/jpeg", "image/png"}:
        raise HTTPException(status_code=415, detail="只接受 JPEG 或 PNG 照片。")
    suffix = ".png" if photo.content_type == "image/png" else ".jpg"
    settings = get_settings()
    photo_dir = settings.data_dir / "photo"
    photo_dir.mkdir(parents=True, exist_ok=True)
    destination = photo_dir / f"photo-{int(time.time() * 1000)}{suffix}"
    await save_upload_stream(
        photo, destination, settings.max_photo_upload_bytes, settings.min_free_disk_bytes, "照片"
    )
    material_id, job_id = repository().create_material_with_job(
        title=(title or "").strip() or Path(photo.filename).stem, source_type="photo", source_ref=photo.filename,
        job_kind="vision", payload={"image_path": str(destination)},
    )
    repository().store_material_thumbnail(material_id, str(destination))
    return {"material_id": material_id, "job_id": job_id, "status": "pending"}


@app.get("/voice-teacher/status")
def voice_teacher_status() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "configured": bool(settings.dashscope_api_key and settings.dashscope_omni_ws_url),
        "model": settings.dashscope_omni_model,
    }


@app.websocket("/voice-teacher/ws")
async def voice_teacher_socket(websocket: WebSocket) -> None:
    await relay_voice_teacher(websocket, get_settings())


@app.get("/voice-profiles")
def get_voice_profiles() -> list[dict]:
    return repository().voice_profiles()


@app.post("/voice-profiles", status_code=status.HTTP_202_ACCEPTED)
async def post_voice_profile(
    name: Annotated[str, Form()],
    prefix: Annotated[str, Form()],
    selection_mode: Annotated[str, Form()] = "auto",
    clip_start_seconds: Annotated[float, Form()] = 0.0,
    clip_duration_seconds: Annotated[float, Form()] = 20.0,
    authorized: Annotated[bool, Form()] = False,
    sample: UploadFile = File(),
) -> dict[str, int | str]:
    if not name.strip():
        raise HTTPException(status_code=422, detail="请填写音色名称。")
    if re.fullmatch(r"[A-Za-z0-9]{1,10}", prefix.strip()) is None:
        raise HTTPException(status_code=422, detail="音色前缀只接受 1–10 个英文字母或数字。")
    if not authorized:
        raise HTTPException(status_code=422, detail="请先确认文件中的声音属于本人或已经获得明确授权。")
    if not sample.filename:
        raise HTTPException(status_code=422, detail="请选择一个日语录音或视频文件。")

    content_type = (sample.content_type or "").lower()
    suffix = Path(sample.filename).suffix.lower()
    video_suffixes = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
    audio_suffixes = {".m4a", ".mp3", ".wav", ".aac", ".caf", ".flac", ".ogg", ".aiff", ".aif"}
    if content_type.startswith("video/") or (
        not content_type.startswith("audio/") and suffix in video_suffixes
    ):
        return await _enqueue_video_voice_profile(
            name=name,
            prefix=prefix,
            selection_mode=selection_mode,
            clip_start_seconds=clip_start_seconds,
            clip_duration_seconds=clip_duration_seconds,
            video=sample,
        )
    if not content_type.startswith("audio/") and suffix not in audio_suffixes:
        raise HTTPException(status_code=415, detail="只接受音频或受支持的视频文件。")

    settings = get_settings()
    suffix = suffix or ".m4a"
    directory = settings.data_dir / "voice-profiles"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"sample-{time.time_ns()}{suffix}"
    await save_upload_stream(
        sample, destination, settings.max_audio_upload_bytes, settings.min_free_disk_bytes, "参考录音"
    )
    try:
        job_id = repository().enqueue_job(
            kind="voice_enrollment",
            material_id=None,
            payload={"name": name.strip()[:160], "prefix": prefix.strip(), "sample_path": str(destination)},
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {"job_id": job_id, "status": "pending", "source_kind": "audio"}


async def _enqueue_video_voice_profile(
    *,
    name: str,
    prefix: str,
    selection_mode: str,
    clip_start_seconds: float,
    clip_duration_seconds: float,
    video: UploadFile,
) -> dict[str, int | str]:
    normalized_mode = selection_mode.strip().lower()
    if normalized_mode not in {"auto", "manual"}:
        raise HTTPException(status_code=422, detail="片段选择方式只支持 auto 或 manual。")
    selected_start = None if normalized_mode == "auto" else clip_start_seconds
    try:
        validate_video_voice_clip(selected_start, clip_duration_seconds)
    except RuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not video.filename:
        raise HTTPException(status_code=422, detail="请选择包含日语人声的视频文件。")
    suffix = Path(video.filename).suffix.lower() or ".mp4"
    if suffix not in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
        raise HTTPException(status_code=415, detail="暂不支持这种视频格式。")

    settings = get_settings()
    directory = settings.data_dir / "voice-profiles" / "video-uploads"
    directory.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(directory).free < settings.min_free_disk_bytes:
        raise HTTPException(status_code=507, detail="本机磁盘空间不足，暂不能接收视频。")
    destination = directory / f"voice-source-{time.time_ns()}{suffix}"
    await save_upload_stream(
        video,
        destination,
        settings.max_video_upload_bytes,
        settings.min_free_disk_bytes,
        "声音复刻视频",
    )
    try:
        job_id = repository().enqueue_job(
            kind="voice_enrollment_video",
            material_id=None,
            payload={
                "name": name.strip()[:160],
                "prefix": prefix.strip(),
                "source_path": str(destination),
                "selection_mode": normalized_mode,
                "clip_start_seconds": selected_start,
                "clip_duration_seconds": clip_duration_seconds,
            },
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {
        "job_id": job_id,
        "status": "pending",
        "source_kind": "video",
        "selection_mode": normalized_mode,
    }


@app.post("/voice-profiles/{profile_id}/default")
def choose_voice_profile(profile_id: int) -> dict[str, int | str]:
    if not repository().set_default_voice_profile(profile_id):
        raise HTTPException(status_code=404, detail="音色不存在。")
    return {"profile_id": profile_id, "status": "default"}


@app.post("/settings/voice-profile", response_class=HTMLResponse)
async def settings_voice_profile(
    name: Annotated[str, Form()],
    prefix: Annotated[str, Form()],
    selection_mode: Annotated[str, Form()] = "auto",
    clip_start_seconds: Annotated[float, Form()] = 0.0,
    clip_duration_seconds: Annotated[float, Form()] = 20.0,
    authorized: Annotated[bool, Form()] = False,
    sample: UploadFile = File(),
) -> RedirectResponse:
    result = await post_voice_profile(
        name=name,
        prefix=prefix,
        selection_mode=selection_mode,
        clip_start_seconds=clip_start_seconds,
        clip_duration_seconds=clip_duration_seconds,
        authorized=authorized,
        sample=sample,
    )
    return RedirectResponse(
        url=f"/settings?voice_job={result['job_id']}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/settings/voice-profile/{profile_id}/default", response_class=HTMLResponse)
def settings_choose_voice_profile(profile_id: int) -> RedirectResponse:
    choose_voice_profile(profile_id)
    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/materials", status_code=status.HTTP_202_ACCEPTED)
def post_material(payload: MaterialCreate) -> dict[str, int | str]:
    material_id, job_id = create_material(payload)
    return {"material_id": material_id, "job_id": job_id, "status": "pending"}


@app.get("/materials")
def get_materials() -> list[dict]:
    return [serialise_material(item) for item in repository().list_materials()]


@app.get("/materials/{material_id}")
def get_material(material_id: int) -> dict:
    material = repository().get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="材料不存在。")
    material["segments"] = repository().get_segments(material_id)
    material["tokens"] = repository().get_tokens(material_id)
    return serialise_material(material)


@app.get("/materials/{material_id}/thumbnail")
def get_material_thumbnail(material_id: int) -> FileResponse:
    path = repository().material_thumbnail_path(material_id)
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="该素材没有可用封面。")
    media_type = "image/png" if Path(path).suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media_type)


@app.get("/materials/{material_id}/playback")
def get_material_playback(material_id: int) -> dict:
    state = repository().get_playback_state(material_id)
    if state is None:
        raise HTTPException(status_code=404, detail="视频素材不存在。")
    return state


@app.put("/materials/{material_id}/playback")
def put_material_playback(material_id: int, payload: PlaybackStateUpdate) -> dict:
    state = repository().save_playback_state(material_id, payload.position_ms)
    if state is None:
        raise HTTPException(status_code=404, detail="视频素材不存在。")
    return state


@app.post("/materials/{material_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_material(material_id: int) -> dict[str, int | str]:
    job_id = repository().retry_failed_material(material_id)
    if job_id is None:
        raise HTTPException(status_code=404, detail="素材不存在。")
    if job_id == 0:
        raise HTTPException(status_code=409, detail="没有可以重新尝试的失败任务。")
    return {"material_id": material_id, "job_id": job_id, "status": "pending"}


def enqueue_video_transcription(material_id: int) -> int:
    repo = repository()
    material = repo.get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="素材不存在。")
    if material["kind"] != "video" or material["status"] != "downloaded":
        raise HTTPException(status_code=409, detail="只有已下载待转录的视频可以开始转录。")
    transcode_payload = repo.latest_transcode_payload(material_id)
    if not transcode_payload or not transcode_payload.get("source_path"):
        raise HTTPException(status_code=409, detail="找不到本地转码记录，无法开始转录。")
    output_dir = get_settings().data_dir / "video" / f"material-{material_id}"
    repo.mark_material_processing(material_id)
    return repo.enqueue_job(
        kind="upload_video",
        material_id=material_id,
        payload={
            "source_path": transcode_payload["source_path"],
            "video_directory": str(output_dir / "hls-video"),
            "audio_directory": str(output_dir / "hls-audio"),
            "asr_audio_path": str(output_dir / "asr-audio.m4a"),
        },
    )


@app.post("/materials/{material_id}/start-transcription", status_code=status.HTTP_202_ACCEPTED)
def start_material_transcription(material_id: int) -> dict[str, int | str]:
    job_id = enqueue_video_transcription(material_id)
    return {"material_id": material_id, "job_id": job_id, "status": "pending"}


@app.get("/materials/{material_id}/segments")
@app.get("/segments")
def get_segments(material_id: int) -> list[dict]:
    material = repository().get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="材料不存在。")
    return repository().get_segments(material_id)


@app.get("/materials/{material_id}/tokens")
@app.get("/tokens")
def get_tokens(material_id: int) -> list[dict]:
    material = repository().get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="材料不存在。")
    return repository().get_tokens(material_id)


def _llm_error(error: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))


@app.get("/companion/{material_id}")
def get_companion_messages(material_id: int) -> list[dict]:
    if repository().get_material(material_id) is None:
        raise HTTPException(status_code=404, detail="材料不存在。")
    return repository().companion_messages(material_id)


@app.post("/companion")
def post_companion(payload: CompanionRequest) -> dict:
    repo = repository()
    if repo.get_material(payload.material_id) is None:
        raise HTTPException(status_code=404, detail="材料不存在。")
    context = repo.segment_context(payload.material_id, payload.segment_id) if payload.segment_id else []
    if payload.segment_id and not context:
        raise HTTPException(status_code=404, detail="该材料中不存在这句话。")
    user = repo.add_companion_message(payload.material_id, payload.segment_id, "user", payload.question.strip())
    history = repo.companion_messages(payload.material_id)[-12:-1]
    messages = build_companion_messages(context=context, history=history, question=payload.question)
    try:
        answer = llm_service().reply(
            messages,
            enable_thinking=False,
            max_tokens=1_200,
        )
    except Exception as error:
        raise _llm_error(error) from error
    assistant = repo.add_companion_message(payload.material_id, payload.segment_id, "assistant", answer)
    return {"user": user, "assistant": assistant}


def _chat_turn(*, topic: str, history: list[dict], guidance: str, user_message: str | None):
    messages = chat_messages(
        topic=topic,
        history=history,
        guidance=guidance,
        user_message=user_message,
    )
    try:
        turn = generate_chat_turn(llm_service(), messages)
    except ChatOutputError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    except Exception as error:
        raise _llm_error(error) from error
    return suppress_follow_up(turn, history)


@app.get("/chat/topics")
def get_chat_topics() -> list[dict]:
    return [topic.model_dump() for topic in STARTER_TOPICS]


@app.post("/chat/sessions", status_code=status.HTTP_201_CREATED)
def create_chat_session(payload: ChatSessionCreate) -> dict:
    try:
        topic, starter_id = topic_for(payload.starter_id, payload.topic)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    repo = repository()
    turn = _chat_turn(
        topic=topic,
        history=[],
        guidance=repo.recent_correction_guidance(),
        user_message=None,
    )
    session, assistant = repo.create_chat_session(
        session_id=str(uuid.uuid4()),
        topic=topic,
        starter_id=starter_id,
        assistant_content=assistant_content(turn),
    )
    return {"session": session, "assistant": assistant}


@app.get("/chat/sessions")
def get_chat_sessions() -> list[dict]:
    return repository().chat_sessions()


@app.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: str) -> dict:
    detail = repository().chat_session_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="聊天会话不存在。")
    return detail


@app.delete("/chat/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_session(session_id: str) -> Response:
    if not repository().delete_chat_session(session_id):
        raise HTTPException(status_code=404, detail="聊天会话不存在。")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/chat/sessions/{session_id}/messages")
def post_chat_message(session_id: str, payload: ChatMessageCreate) -> dict:
    repo = repository()
    session = repo.get_chat_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="聊天会话不存在。")
    message = payload.message.strip()
    turn = _chat_turn(
        topic=str(session["topic"]),
        history=repo.chat_messages(session_id)[-20:],
        guidance=repo.recent_correction_guidance(),
        user_message=message,
    )
    user, correction, assistant = repo.complete_chat_turn(
        session_id=session_id,
        user_content=message,
        assistant_content=assistant_content(turn),
        correction=correction_payload(turn),
    )
    return {"user": user, "correction": correction, "assistant": assistant}


@app.get("/chat/corrections")
def get_chat_corrections(
    query: str = Query(default="", max_length=200),
    topic: str | None = Query(default=None, max_length=160),
    category: str | None = Query(default=None, max_length=40),
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict]:
    allowed = {"grammar", "word_choice", "naturalness", "register", "orthography"}
    if category is not None and category not in allowed:
        raise HTTPException(status_code=422, detail="不支持的纠错类别。")
    return repository().chat_corrections(
        query=query,
        topic=topic,
        category=category,
        cursor=cursor,
        limit=limit,
    )


@app.delete("/chat/corrections/{correction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_correction(correction_id: int) -> Response:
    if not repository().delete_chat_correction(correction_id):
        raise HTTPException(status_code=404, detail="纠错记录不存在。")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# One-release compatibility layer for the already-installed iPhone build.
@app.get("/chat/{session_id}")
def get_chat_messages(session_id: str) -> list[dict]:
    return repository().chat_messages(session_id)


@app.post("/chat")
def post_chat(payload: ChatRequest) -> dict:
    repo = repository()
    session = repo.get_chat_session(payload.session_id)
    topic = str(session["topic"]) if session is not None else "旧版聊天"
    message = payload.message.strip()
    turn = _chat_turn(
        topic=topic,
        history=repo.chat_messages(payload.session_id)[-20:],
        guidance=repo.recent_correction_guidance(),
        user_message=message,
    )
    user, correction, assistant = repo.complete_chat_turn(
        session_id=payload.session_id,
        user_content=message,
        assistant_content=assistant_content(turn),
        correction=correction_payload(turn),
        create_session_topic=topic,
    )
    return {"user": user, "correction": correction, "assistant": assistant}


class FuriganaRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)


@app.post("/furigana")
def furigana(payload: FuriganaRequest) -> dict[str, object]:
    try:
        segments = ruby_segments(payload.text)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"segments": segments}


# ── dictionary & vocabulary ────────────────────────────────────

class DictionaryLookupRequest(BaseModel):
    word: str = Field(min_length=1, max_length=100)
    context: str | None = None


_DICTIONARY_SYSTEM = (
    "你是一个日语词典助手，使用者是中文母语的日语学习者。"
    "你返回读音、释义、词性、便于记忆的提示，以及例句。\n\n"
    "规则：\n"
    "- reading：该词的平假名读音\n"
    "- meaning：简洁中文核心释义；若词有明显多义，只给最常用的 1–2 个，不要堆砌\n"
    "- part_of_speech：用中文标注（他動詞／自動詞／い形容詞／な形容詞／名詞／副詞／助詞／接続詞 等）\n"
    "- memory_hint：一句简短中文记忆钩子，按下列优先级选择角度——\n"
    "  ① 该词与中文同形但语感、适用场景或搭配不同时，优先点明这个差异（中文里是什么、"
    "日语里是什么、为什么不能照搬）。这类词最容易因为「看得懂」而被误用，价值最高；\n"
    "  ② 含汉字时，拆解汉字各自的含义如何合成该词义，让使用者能挂在已有的汉字知识上；\n"
    "  ③ 以上都不适用时，再给语感、常见搭配、易混点或具体场景联想。\n"
    "  要具体可记、说清成因而不只给结论；不要空泛鼓励，不要复述释义原文，不要为了套用①而牵强附会；"
    "不使用 emoji 或装饰性符号\n"
    "- examples：2 或 3 个自然、短小的当代日语例句，每句必须包含被查的词本身；"
    "zh 为对应简洁中文翻译；不要罗马字，不要解释语法长文\n"
    "- 不确定时在 meaning 里写「待确认：…」，不要编造冷僻义项\n\n"
    "只返回一个 JSON 对象，不要任何其他文字：\n"
    '{"reading":"平假名","meaning":"中文释义","part_of_speech":"词性",'
    '"memory_hint":"记忆提示","examples":[{"ja":"日语例句","zh":"中文翻译"}]}'
)


def _dictionary_lookup(*, word: str, context: str | None) -> dict[str, object]:
    cleaned = word.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="请提供要查询的词。")
    user_prompt = f"请解释并给出记忆提示与例句：{cleaned}"
    if context and context.strip():
        user_prompt += f"\n\n（可选参考上下文，不必复述）：{context.strip()}"
    messages = [
        {"role": "system", "content": _DICTIONARY_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    try:
        raw = llm_service().reply(messages, enable_thinking=False, json_mode=True, max_tokens=900)
    except Exception as error:
        raise _llm_error(error) from error
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=503, detail="词典服务返回格式异常，请重试。") from error
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="词典服务返回格式异常，请重试。")

    normalized: dict[str, object] = {}
    for key in ("reading", "meaning", "part_of_speech", "memory_hint"):
        value = result.get(key)
        if value is None:
            normalized[key] = None
        else:
            text = str(value).strip()
            normalized[key] = text or None

    examples: list[dict[str, str]] = []
    raw_examples = result.get("examples")
    if isinstance(raw_examples, list):
        for item in raw_examples:
            if not isinstance(item, dict):
                continue
            ja = str(item.get("ja") or "").strip()
            zh = str(item.get("zh") or "").strip()
            if not ja or not zh:
                continue
            examples.append({"ja": ja, "zh": zh})
            if len(examples) >= 3:
                break
    normalized["examples"] = examples
    return normalized


class DictionaryLookupResponse(BaseModel):
    word: str
    reading: str | None = None
    meaning: str | None = None
    part_of_speech: str | None = None
    memory_hint: str | None = None
    examples: list[dict[str, str]] = []


@app.post("/dictionary/lookup")
def dictionary_lookup(payload: DictionaryLookupRequest) -> dict:
    result = _dictionary_lookup(word=payload.word, context=payload.context)
    return {
        "word": payload.word.strip(),
        "reading": result.get("reading"),
        "meaning": result.get("meaning"),
        "part_of_speech": result.get("part_of_speech"),
        "memory_hint": result.get("memory_hint"),
        "examples": result.get("examples") or [],
    }


class VocabularyCreate(BaseModel):
    word: str = Field(min_length=1, max_length=100)
    reading: str | None = None
    meaning: str | None = None
    part_of_speech: str | None = None
    context: str | None = None
    example_ja: str | None = None
    example_zh: str | None = None

    @field_validator("example_ja", "example_zh")
    @classmethod
    def _example_requires_pair(cls, value: str | None) -> str | None:
        stripped = value.strip() if value else None
        return stripped or None


@app.post("/vocabulary", status_code=status.HTTP_201_CREATED)
def add_vocabulary(payload: VocabularyCreate) -> dict:
    meaning = (payload.meaning or "").strip()
    if not meaning:
        raise HTTPException(status_code=422, detail="释义不能为空。")
    # A cloze review needs both sides of the example; drop a lone half.
    example_ja = payload.example_ja
    example_zh = payload.example_zh
    if not (example_ja and example_zh):
        example_ja = None
        example_zh = None
    row, already_saved = repository().add_vocabulary(
        word=payload.word.strip(),
        reading=(payload.reading or None),
        meaning=meaning,
        part_of_speech=(payload.part_of_speech or None),
        context=payload.context,
        example_ja=example_ja,
        example_zh=example_zh,
    )
    # Lets the client say "已在生词表" instead of claiming a fresh save.
    return {**row, "already_saved": already_saved}


@app.get("/vocabulary")
def list_vocabulary() -> list[dict]:
    return repository().list_vocabulary()


@app.delete("/vocabulary/{vocabulary_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vocabulary(vocabulary_id: int) -> Response:
    deleted = repository().delete_vocabulary(vocabulary_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="生词不存在。")


@app.get("/vocabulary/review")
def review_vocabulary(limit: int = Query(default=20, ge=1, le=50)) -> list[dict]:
    return repository().list_due_vocabulary(limit=limit)


class VocabularyReviewResult(BaseModel):
    correct: bool


@app.post("/vocabulary/{vocabulary_id}/review")
def submit_vocabulary_review(vocabulary_id: int, payload: VocabularyReviewResult) -> dict:
    updated = repository().record_vocabulary_review(vocabulary_id, correct=payload.correct)
    if updated is None:
        raise HTTPException(status_code=404, detail="生词不存在。")
    return updated
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/shadowing", status_code=status.HTTP_202_ACCEPTED)
async def post_shadowing(segment_id: int = Form(), audio: UploadFile = File()) -> dict[str, int | str]:
    repo = repository()
    if repo.get_segment(segment_id) is None:
        raise HTTPException(status_code=404, detail="原句不存在。")
    if not audio.filename or not (audio.content_type or "").startswith("audio/"):
        raise HTTPException(status_code=415, detail="请选择音频格式的跟读录音。")
    suffix = Path(audio.filename).suffix.lower()
    if suffix not in {".m4a", ".mp3", ".wav", ".aac", ".caf", ".mp4"}:
        suffix = ".m4a"
    settings = get_settings()
    shadow_dir = settings.data_dir / "shadowing"
    shadow_dir.mkdir(parents=True, exist_ok=True)
    destination = shadow_dir / f"upload-{segment_id}-{time.time_ns()}{suffix}"
    await save_upload_stream(
        audio, destination, settings.max_audio_upload_bytes, settings.min_free_disk_bytes, "跟读录音"
    )
    try:
        attempt_id, job_id = repo.create_shadowing_submission(segment_id, str(destination))
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {"attempt_id": attempt_id, "job_id": job_id, "status": "pending"}


async def save_upload_stream(
    upload: UploadFile,
    destination: Path,
    max_bytes: int,
    min_free_bytes: int,
    kind_label: str = "文件",
) -> None:
    """Copy an upload incrementally while preserving a minimum free-space reserve."""
    written = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail=f"{kind_label}超过允许的大小。")
                if shutil.disk_usage(destination.parent).free - len(chunk) < min_free_bytes:
                    raise HTTPException(status_code=507, detail="本机磁盘空间不足，上传已停止。")
                await asyncio.to_thread(output.write, chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


@app.get("/shadowing/{attempt_id}")
def get_shadowing(attempt_id: int) -> dict:
    attempt = repository().get_shadowing_attempt(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="跟读记录不存在。")
    return attempt


@app.get("/jobs/{job_id}")
def get_job(job_id: int) -> dict:
    job = repository().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return job


@app.get("/admin/materials", response_class=HTMLResponse)
def admin_materials_page(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
) -> HTMLResponse:
    repo = repository()
    total = repo.count_materials(status=status_filter)
    materials = repo.list_materials(status=status_filter, limit=limit, offset=(page - 1) * limit)
    return templates.TemplateResponse(
        request,
        "materials.html",
        page_context(
            "materials",
            materials=materials,
            total=total,
            page=page,
            limit=limit,
            pages=max(1, (total + limit - 1) // limit),
            status_filter=status_filter,
        ),
    )


@app.post("/admin/materials/{material_id}/start-transcription", response_class=HTMLResponse)
def start_transcription(material_id: int) -> RedirectResponse:
    enqueue_video_transcription(material_id)
    return RedirectResponse(url="/admin/materials", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/jobs", response_class=HTMLResponse)
def admin_jobs_page(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    kind: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
) -> HTMLResponse:
    repo = repository()
    total = repo.count_jobs(status=status_filter, kind=kind)
    jobs = repo.list_jobs(status=status_filter, kind=kind, limit=limit, offset=(page - 1) * limit)
    return templates.TemplateResponse(
        request,
        "jobs.html",
        page_context(
            "jobs",
            jobs=jobs,
            total=total,
            page=page,
            limit=limit,
            pages=max(1, (total + limit - 1) // limit),
            status_filter=status_filter,
            kind=kind,
            job_kinds=_JOB_KINDS,
        ),
    )


@app.get("/ingest-web", response_class=HTMLResponse)
def ingest_page(
    request: Request,
    created: int | None = None,
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "ingest.html",
        page_context("ingest", error=error, created_material_id=created),
    )


@app.post("/ingest-web", response_class=HTMLResponse)
def ingest_form(
    request: Request,
    title: Annotated[str | None, Form()] = None,
    source_text: Annotated[str | None, Form()] = None,
    source_url: Annotated[str | None, Form()] = None,
):
    try:
        material_id, _ = create_material(MaterialCreate(title=title, text=source_text, url=source_url))
    except ValueError as error:
        return templates.TemplateResponse(
            request, "ingest.html", page_context("ingest", error=str(error)), status_code=422
        )
    return RedirectResponse(url=f"/ingest-web?created={material_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/ingest-web/video-file", response_class=HTMLResponse)
async def ingest_video_file(
    title: Annotated[str | None, Form()] = None,
    video: UploadFile = File(),
) -> RedirectResponse:
    result = await post_video(title=title, video=video)
    return RedirectResponse(
        url=f"/ingest-web?created={result['material_id']}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/ingest-web/video-link", response_class=HTMLResponse)
def ingest_video_link(
    title: Annotated[str | None, Form()] = None,
    video_url: Annotated[str, Form()] = "",
) -> RedirectResponse:
    material_id, _ = create_video_link(VideoLinkCreate(title=title, url=video_url))
    return RedirectResponse(url=f"/ingest-web?created={material_id}", status_code=status.HTTP_303_SEE_OTHER)
