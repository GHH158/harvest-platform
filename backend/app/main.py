from __future__ import annotations

import asyncio
import os
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Engine

from .config import ROOT_DIR, get_settings
from .db import apply_schema, make_engine
from .llm import LLMService
from .repository import Repository
from .storage import ObjectStorage


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


def title_for_text(value: str) -> str:
    first_line = next((line.strip() for line in value.splitlines() if line.strip()), "未命名材料")
    return f"{first_line[:36]}{'…' if len(first_line) > 36 else ''}"


def title_for_url(value: str) -> str:
    return urlparse(value).netloc or "网页材料"


def serialise_material(material: dict) -> dict:
    settings = get_settings()
    audio_key = material.pop("audio_oss_key", None)
    video_key = material.pop("video_oss_key", None)
    material["audio_url"] = (
        f"{settings.oss_public_base_url.rstrip('/')}/{audio_key}" if audio_key and settings.oss_public_base_url else None
    )
    material["video_url"] = (
        f"{settings.oss_public_base_url.rstrip('/')}/{video_key}"
        if video_key and settings.oss_public_base_url
        else None
    )
    return material


_engine: Engine | None = None
_repository: Repository | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _engine, _repository
    engine = make_engine()
    try:
        apply_schema(engine)
        _engine = engine
        _repository = Repository(engine)
        yield
    finally:
        engine.dispose()
        if _engine is engine:
            _engine = None
            _repository = None


app = FastAPI(title="Harvest", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT_DIR / "backend" / "app" / "static"), name="static")
templates = Jinja2Templates(directory=ROOT_DIR / "backend" / "app" / "templates")


def repository() -> Repository:
    if _repository is None:
        raise RuntimeError("应用数据库尚未初始化。")
    return _repository


_SETTINGS_KEYS = (
    "DATABASE_URL", "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL", "DASHSCOPE_TTS_MODEL",
    "DASHSCOPE_TTS_VOICE", "DASHSCOPE_ASR_MODEL", "DASHSCOPE_CHAT_BASE_URL",
    "DASHSCOPE_CHAT_MODEL", "DASHSCOPE_OMNI_MODEL", "DASHSCOPE_VL_MODEL",
    "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL", "OSS_ENDPOINT", "OSS_BUCKET", "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET",
    "OSS_PUBLIC_BASE_URL", "OSS_TEMPORARY_RETENTION_DAYS", "OSS_SHADOWING_RETENTION_DAYS",
    "TAILSCALE_HOSTNAME", "MAX_VIDEO_UPLOAD_BYTES", "MIN_FREE_DISK_BYTES",
)
_SECRET_KEYS = {"DATABASE_URL", "DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY", "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET"}


def _update_env(values: dict[str, str]) -> None:
    env_path = ROOT_DIR / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    remaining = {key: value for key, value in values.items() if key in _SETTINGS_KEYS and value.strip()}
    updated: list[str] = []
    for line in lines:
        key = line.partition("=")[0]
        if key in remaining:
            updated.append(f"{key}={remaining.pop(key)}")
        else:
            updated.append(line)
    updated.extend(f"{key}={value}" for key, value in remaining.items())
    env_path.write_text("\n".join(updated) + "\n")
    os.chmod(env_path, 0o600)
    get_settings.cache_clear()


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
def settings_page(request: Request, saved: int | None = None) -> HTMLResponse:
    return templates.TemplateResponse(request, "settings.html", settings_context(saved=saved))


def settings_context(**messages: object) -> dict[str, object]:
    settings = get_settings()
    secret_status = {key: bool(getattr(settings, key.lower(), None)) for key in _SECRET_KEYS}
    values = {key: getattr(settings, key.lower(), "") for key in _SETTINGS_KEYS if key not in _SECRET_KEYS}
    return {"status": secret_status, "values": values, **messages}


@app.post("/settings", response_class=HTMLResponse)
async def save_settings(request: Request) -> RedirectResponse:
    form = await request.form()
    _update_env({key: str(form.get(key, "")) for key in _SETTINGS_KEYS})
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
    await save_upload_stream(video, destination, settings.max_video_upload_bytes, settings.min_free_disk_bytes)
    material_id, job_id = repository().create_material_with_job(
        kind="video", title=(title or "").strip() or Path(video.filename).stem,
        source_type="file", source_ref=video.filename, job_kind="transcode", payload={"source_path": str(destination)},
    )
    return {"material_id": material_id, "job_id": job_id, "status": "pending"}


@app.post("/photos", status_code=status.HTTP_202_ACCEPTED)
async def post_photo(title: Annotated[str | None, Form()] = None, photo: UploadFile = File()) -> dict[str, int | str]:
    if not photo.filename:
        raise HTTPException(status_code=422, detail="请选择一张照片。")
    suffix = Path(photo.filename).suffix or ".jpg"
    photo_dir = get_settings().data_dir / "photo"
    photo_dir.mkdir(parents=True, exist_ok=True)
    destination = photo_dir / f"photo-{int(time.time() * 1000)}{suffix}"
    destination.write_bytes(await photo.read())
    material_id, job_id = repository().create_material_with_job(
        title=(title or "").strip() or Path(photo.filename).stem, source_type="photo", source_ref=photo.filename,
        job_kind="vision", payload={"image_path": str(destination)},
    )
    return {"material_id": material_id, "job_id": job_id, "status": "pending"}


@app.get("/voice-teacher/status")
def voice_teacher_status() -> dict[str, str | bool]:
    settings = get_settings()
    return {"configured": bool(settings.dashscope_api_key), "model": settings.dashscope_omni_model}


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
    context_text = "\n".join(f"{item['idx'] + 1}. {item['text_ja']}" for item in context) or "（未指定句子）"
    messages: list[dict[str, str]] = [
        {"role": "system", "content": "你是克制、耐心的日语陪读老师。用中文解释，必要时给简短日语例句。"},
    ]
    history = repo.companion_messages(payload.material_id)[-12:-1]
    messages.extend({"role": item["role"], "content": item["content"]} for item in history)
    messages.append({"role": "user", "content": f"阅读上下文：\n{context_text}\n\n问题：{payload.question.strip()}"})
    try:
        answer = LLMService(get_settings()).reply(messages)
    except Exception as error:
        raise _llm_error(error) from error
    assistant = repo.add_companion_message(payload.material_id, payload.segment_id, "assistant", answer)
    return {"user": user, "assistant": assistant}


@app.get("/chat/{session_id}")
def get_chat_messages(session_id: str) -> list[dict]:
    return repository().chat_messages(session_id)


@app.post("/chat")
def post_chat(payload: ChatRequest) -> dict:
    repo = repository()
    user = repo.add_chat_message(payload.session_id, "user", payload.message.strip())
    history = repo.chat_messages(payload.session_id)[-16:]
    messages = [{"role": "system", "content": "你是日语聊天老师。以日语自然回应，并在需要时用简短中文帮助理解。"}]
    messages.extend({"role": item["role"], "content": item["content"]} for item in history)
    try:
        answer = LLMService(get_settings()).reply(messages)
    except Exception as error:
        raise _llm_error(error) from error
    assistant = repo.add_chat_message(payload.session_id, "assistant", answer)
    return {"user": user, "assistant": assistant}


@app.post("/shadowing", status_code=status.HTTP_202_ACCEPTED)
async def post_shadowing(segment_id: int = Form(), audio: UploadFile = File()) -> dict[str, int | str]:
    repo = repository()
    if repo.get_segment(segment_id) is None:
        raise HTTPException(status_code=404, detail="原句不存在。")
    suffix = ".m4a" if not audio.filename else f".{audio.filename.rsplit('.', 1)[-1]}"
    shadow_dir = get_settings().data_dir / "shadowing"
    shadow_dir.mkdir(parents=True, exist_ok=True)
    placeholder = shadow_dir / f"pending-{segment_id}{suffix}"
    attempt_id = repo.create_shadowing_attempt(segment_id, str(placeholder))
    destination = shadow_dir / f"attempt-{attempt_id}{suffix}"
    destination.write_bytes(await audio.read())
    repo.update_shadowing_audio_path(attempt_id, str(destination))
    job_id = repo.enqueue_job(
        kind="shadowing", material_id=None,
        payload={"attempt_id": attempt_id, "segment_id": segment_id, "audio_path": str(destination)},
    )
    repo.attach_shadowing_job(attempt_id, job_id)
    return {"attempt_id": attempt_id, "job_id": job_id, "status": "pending"}


async def save_upload_stream(upload: UploadFile, destination: Path, max_bytes: int, min_free_bytes: int) -> None:
    """Copy an upload incrementally while preserving a minimum free-space reserve."""
    written = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail="视频超过允许的大小。")
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


@app.get("/ingest-web", response_class=HTMLResponse)
def ingest_page(
    request: Request,
    created: int | None = None,
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "ingest.html",
        {"error": error, "created_material_id": created},
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
        return templates.TemplateResponse(request, "ingest.html", {"error": str(error)}, status_code=422)
    return RedirectResponse(url=f"/ingest-web?created={material_id}", status_code=status.HTTP_303_SEE_OTHER)
