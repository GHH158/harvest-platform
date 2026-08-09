from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app import main
from app.config import Settings
from app.llm import LLMReply
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers
from starlette.requests import Request


class SubmissionRepository:
    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None
        self.thumbnail: tuple[int, str] | None = None
        self.existing_material: dict[str, Any] | None = None

    def create_material_with_job(self, **values: Any) -> tuple[int, int]:
        self.created = values
        return 41, 73

    def find_material_by_source_url(self, url: str) -> dict[str, Any] | None:
        return self.existing_material

    def store_material_thumbnail(self, material_id: int, local_path: str) -> None:
        self.thumbnail = material_id, local_path


class ShadowingRepository:
    submission: tuple[int, str] | None = None

    def get_segment(self, segment_id: int) -> dict[str, int]:
        return {"id": segment_id}

    def create_shadowing_submission(self, segment_id: int, audio_path: str) -> tuple[int, int]:
        self.submission = segment_id, audio_path
        return 51, 82


class StandaloneJobRepository:
    def __init__(self) -> None:
        self.enqueued: dict[str, Any] | None = None

    def enqueue_job(self, **values: Any) -> int:
        self.enqueued = values
        return 91


class PlaybackRepository:
    def __init__(self) -> None:
        self.position_ms = 12_000

    def get_playback_state(self, material_id: int) -> dict[str, Any] | None:
        if material_id != 7:
            return None
        return {"material_id": material_id, "position_ms": self.position_ms, "updated_at": "2026-08-05T00:00:00Z"}

    def save_playback_state(self, material_id: int, position_ms: int) -> dict[str, Any] | None:
        if material_id != 7:
            return None
        self.position_ms = position_ms
        return {"material_id": material_id, "position_ms": position_ms, "updated_at": "2026-08-05T00:01:00Z"}


def upload(filename: str, content_type: str, content: bytes) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def test_photo_submission_uses_material_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repository = SubmissionRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "get_settings", lambda: Settings(data_dir=tmp_path))

    result = asyncio.run(main.post_photo(photo=upload("page.jpg", "image/jpeg", b"photo")))

    assert result == {"material_id": 41, "job_id": 73, "status": "pending"}
    assert repository.created is not None
    assert repository.created["job_kind"] == "vision"
    assert repository.thumbnail is not None
    assert repository.thumbnail[0] == 41
    assert Path(repository.thumbnail[1]).read_bytes() == b"photo"


def test_material_projection_exposes_stage_progress_and_failure_details(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: Settings(data_dir=tmp_path))
    processing = main.serialise_material(
        {
            "id": 7,
            "status": "processing",
            "error_message": None,
            "audio_oss_key": None,
            "video_oss_key": None,
            "thumbnail_local_path": str(tmp_path / "cover.jpg"),
            "current_job_id": 17,
            "current_job_kind": "asr_video",
            "current_job_status": "running",
            "current_job_error_message": None,
            "current_job_payload": {},
            "current_job_updated_at": datetime.now(UTC),
        }
    )
    assert processing["progress_label"] == "正在转录字幕"
    assert processing["progress_percent"] == 82
    assert processing["eta_minutes"] == 5
    assert processing["thumbnail_path"] == "/materials/7/thumbnail"

    failed = main.serialise_material(
        {
            "id": 8,
            "status": "failed",
            "error_message": "Read timed out while connecting to OSS",
            "audio_oss_key": None,
            "video_oss_key": None,
            "thumbnail_local_path": None,
            "current_job_id": 18,
            "current_job_kind": "asr_video",
            "current_job_status": "failed",
            "current_job_error_message": "Read timed out while connecting to OSS",
            "current_job_payload": {},
            "current_job_updated_at": datetime.now(UTC),
        }
    )
    assert failed["failure_title"] == "转录失败"
    assert failed["failure_summary"] == "网络连接中断"
    assert failed["retryable"] is True


def test_video_playback_position_can_be_read_and_updated(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = PlaybackRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)

    assert main.get_material_playback(7)["position_ms"] == 12_000
    updated = main.put_material_playback(7, main.PlaybackStateUpdate(position_ms=34_500))

    assert updated["position_ms"] == 34_500
    assert repository.position_ms == 34_500


def test_playback_position_rejects_unknown_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reading materials keep a position too, so the only rejection left is a
    # material that does not exist.
    monkeypatch.setattr(main, "repository", PlaybackRepository)

    with pytest.raises(HTTPException) as caught:
        main.get_material_playback(99)
    assert caught.value.status_code == 404

    with pytest.raises(HTTPException) as caught:
        main.put_material_playback(99, main.PlaybackStateUpdate(position_ms=1_000))
    assert caught.value.status_code == 404


def test_video_upload_rejects_wrong_type_before_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: Settings(data_dir=tmp_path))

    with pytest.raises(HTTPException) as caught:
        asyncio.run(main.post_video(video=upload("notes.txt", "text/plain", b"not video")))

    assert caught.value.status_code == 415
    assert not list(tmp_path.rglob("*"))


def test_video_upload_stops_at_size_limit_and_removes_partial_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        max_video_upload_bytes=3,
        min_free_disk_bytes=0,
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(main.post_video(video=upload("movie.mp4", "video/mp4", b"1234")))

    assert caught.value.status_code == 413
    assert list((tmp_path / "video" / "uploads").iterdir()) == []


def test_unified_voice_endpoint_dispatches_audio_without_video_preprocessing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = StandaloneJobRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(data_dir=tmp_path, max_audio_upload_bytes=100, min_free_disk_bytes=0),
    )

    result = asyncio.run(
        main.post_voice_profile(
            name="我的录音",
            prefix="audio",
            authorized=True,
            sample=upload("voice.m4a", "audio/m4a", b"voice"),
        )
    )

    assert result == {"job_id": 91, "status": "pending", "source_kind": "audio"}
    assert repository.enqueued is not None
    assert repository.enqueued["kind"] == "voice_enrollment"
    assert repository.enqueued["payload"]["name"] == "我的录音"
    assert Path(repository.enqueued["payload"]["sample_path"]).read_bytes() == b"voice"


def test_unified_voice_endpoint_dispatches_video_to_demucs_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = StandaloneJobRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(data_dir=tmp_path, max_video_upload_bytes=100, min_free_disk_bytes=0),
    )

    result = asyncio.run(
        main.post_voice_profile(
            name="我的视频",
            prefix="video",
            authorized=True,
            sample=upload("voice.mov", "video/quicktime", b"video"),
        )
    )

    assert result == {
        "job_id": 91,
        "status": "pending",
        "source_kind": "video",
        "selection_mode": "auto",
    }
    assert repository.enqueued is not None
    assert repository.enqueued["kind"] == "voice_enrollment_video"
    assert repository.enqueued["material_id"] is None
    assert repository.enqueued["payload"]["clip_start_seconds"] is None
    assert Path(repository.enqueued["payload"]["source_path"]).read_bytes() == b"video"


def test_video_voice_enrollment_requires_explicit_authorization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = StandaloneJobRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "get_settings", lambda: Settings(data_dir=tmp_path))

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            main.post_voice_profile(
                name="未授权声音",
                prefix="mine",
                authorized=False,
                sample=upload("voice.mp4", "video/mp4", b"video"),
            )
        )

    assert caught.value.status_code == 422
    assert "授权" in str(caught.value.detail)
    assert repository.enqueued is None
    assert not list(tmp_path.rglob("*"))


def test_video_link_creates_download_job(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = SubmissionRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)

    result = main.post_video_link(main.VideoLinkCreate(url="https://example.com/watch/1"))

    assert result == {"material_id": 41, "job_id": 73, "status": "pending"}
    assert repository.created is not None
    assert repository.created["kind"] == "video"
    assert repository.created["job_kind"] == "download_video"


def test_video_link_already_imported_is_rejected_instead_of_downloaded_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SubmissionRepository()
    repository.existing_material = {"id": 32, "title": "日本で人気", "status": "ready"}
    monkeypatch.setattr(main, "repository", lambda: repository)

    with pytest.raises(HTTPException) as caught:
        main.post_video_link(main.VideoLinkCreate(url="https://youtu.be/AgWRJo8n8L8?si=zLpnn"))

    assert caught.value.status_code == 409
    assert "#32" in caught.value.detail
    # The expensive part must not start.
    assert repository.created is None


def test_reimporting_a_failed_link_points_at_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = SubmissionRepository()
    repository.existing_material = {"id": 29, "title": "日本の雨", "status": "failed"}
    monkeypatch.setattr(main, "repository", lambda: repository)

    with pytest.raises(HTTPException) as caught:
        main.post_video_link(main.VideoLinkCreate(url="https://youtu.be/AgWRJo8n8L8"))

    assert caught.value.status_code == 409
    assert "重试" in caught.value.detail
    assert repository.created is None


def test_photo_upload_streams_and_enforces_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(data_dir=tmp_path, max_photo_upload_bytes=3, min_free_disk_bytes=0),
    )

    with pytest.raises(HTTPException) as caught:
        asyncio.run(main.post_photo(photo=upload("page.jpg", "image/jpeg", b"1234")))

    assert caught.value.status_code == 413
    assert list((tmp_path / "photo").iterdir()) == []


def test_shadowing_upload_is_saved_before_database_submission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = ShadowingRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(data_dir=tmp_path, max_audio_upload_bytes=10, min_free_disk_bytes=0),
    )

    result = asyncio.run(
        main.post_shadowing(segment_id=9, audio=upload("attempt.m4a", "audio/m4a", b"voice"))
    )

    assert result == {"attempt_id": 51, "job_id": 82, "status": "pending"}
    assert repository.submission is not None
    assert Path(repository.submission[1]).read_bytes() == b"voice"


def test_shadowing_oversize_upload_creates_no_submission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = ShadowingRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(data_dir=tmp_path, max_audio_upload_bytes=3, min_free_disk_bytes=0),
    )

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            main.post_shadowing(segment_id=9, audio=upload("attempt.m4a", "audio/m4a", b"voice"))
        )

    assert caught.value.status_code == 413
    assert repository.submission is None
    assert list((tmp_path / "shadowing").iterdir()) == []


def test_settings_can_explicitly_clear_a_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DASHSCOPE_API_KEY=secret\nDEEPSEEK_MODEL=old\n")
    monkeypatch.setattr(main, "ROOT_DIR", tmp_path)

    main._update_env({"DEEPSEEK_MODEL": "deepseek-v4-flash"}, {"DASHSCOPE_API_KEY"})

    assert (tmp_path / ".env").read_text() == "DASHSCOPE_API_KEY=\nDEEPSEEK_MODEL=deepseek-v4-flash\n"


def test_lifespan_creates_one_shared_engine_and_disposes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = SimpleNamespace(dispose_calls=0)

    def dispose() -> None:
        engine.dispose_calls += 1

    engine.dispose = dispose
    calls: list[object] = []
    monkeypatch.setattr(main, "make_engine", lambda: calls.append(object()) or engine)
    monkeypatch.setattr(main, "apply_schema", lambda value: calls.append(value))
    monkeypatch.setattr(main.Repository, "sync_grammar_catalogue", lambda self: calls.append("grammar"))
    monkeypatch.setattr(main.Repository, "backfill_learning_events", lambda self: calls.append("backfill"))
    main._engine = None
    main._repository = None

    async def exercise() -> None:
        async with main.lifespan(main.app):
            first = main.repository()
            second = main.repository()
            assert first is second
            assert first.engine is engine

    asyncio.run(exercise())

    assert len(calls) == 4
    assert calls[1] is engine
    assert calls[2] == "grammar"
    assert calls[3] == "backfill"
    assert engine.dispose_calls == 1
    with pytest.raises(RuntimeError, match="尚未初始化"):
        main.repository()


def test_settings_page_applies_oss_lifecycle_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    class RecordingStorage:
        def __init__(self, settings: Settings) -> None:
            pass

        def configure_lifecycle(self) -> list[dict[str, int | str]]:
            return [{"id": "harvest-temporary-asr", "prefix": "temporary/", "days": 1}]

    monkeypatch.setattr(main, "ObjectStorage", RecordingStorage)
    request = Request({"type": "http", "method": "POST", "path": "/settings/oss-lifecycle", "headers": []})

    response = main.apply_oss_lifecycle(request)

    assert response.status_code == 200
    assert "temporary/" in response.body.decode()


class CompanionRepository:
    def __init__(self) -> None:
        self.messages = [
            {"id": 1, "role": "user", "content": "之前的问题", "created_at": "now"},
            {"id": 2, "role": "assistant", "content": "之前的回答", "created_at": "now"},
        ]
        self.grammar_links: list[tuple[int, list[str], dict[str, Any] | None]] = []

    def get_material(self, material_id: int) -> dict[str, Any]:
        return {"id": material_id}

    def segment_context(self, material_id: int, segment_id: int) -> list[dict[str, Any]]:
        return [{"id": segment_id, "idx": 0, "text_ja": "雨です。"}]

    def add_companion_message(
        self, material_id: int, segment_id: int | None, role: str, content: str, lens: str | None = None
    ) -> dict[str, Any]:
        message = {
            "id": len(self.messages) + 1,
            "role": role,
            "content": content,
            "lens": lens,
            "created_at": "now",
        }
        self.messages.append(message)
        return message

    def companion_messages(self, material_id: int) -> list[dict[str, Any]]:
        return self.messages

    def grammar_catalogue_for_prompt(self) -> list[tuple[str, str, str, str, str]]:
        return [("verb-te", "～て", "て形与连接", "N5", "动词变形")]

    def record_companion_grammar_evidence(
        self,
        message_id: int,
        keys: list[str],
        *,
        decision_context: dict[str, Any] | None = None,
    ) -> list[str]:
        self.grammar_links.append((message_id, keys, decision_context))
        return keys


def test_companion_sends_prior_turns_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = CompanionRepository()
    captured: list[dict[str, str]] = []
    options: list[dict[str, Any]] = []

    class RecordingLLM:
        def reply(self, messages: list[dict[str, str]], **values: Any) -> str:
            captured.extend(messages)
            options.append(values)
            return '{"answer_markdown":"新的回答","grammar_keys":[]}'

    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "llm_service", lambda: RecordingLLM())

    result = main.post_companion(main.CompanionRequest(material_id=7, segment_id=3, question="请解释「流会」的意思"))

    assert [item["content"] for item in captured[1:3]] == ["之前的问题", "之前的回答"]
    assert "只作语境参考,不是日语词汇的全集" in captured[-1]["content"]
    assert captured[-1]["content"].endswith("用户问题:\n请解释「流会」的意思")
    assert options == [{"enable_thinking": False, "json_mode": True, "max_tokens": 1_200}]
    assert result["assistant"]["content"] == "新的回答"
    assert repository.grammar_links == []


def test_companion_records_only_valid_explicit_grammar_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = CompanionRepository()

    class RecordingLLM:
        def reply(self, messages: list[dict[str, str]], **values: Any) -> str:
            return '{"answer_markdown":"这里是て形。","grammar_keys":["verb-te","invented"]}'

    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "llm_service", lambda: RecordingLLM())

    result = main.post_companion(main.CompanionRequest(material_id=7, segment_id=3, question="这里为什么用て形？"))

    assert result["assistant"]["content"] == "这里是て形。"
    assert repository.grammar_links == [
        (
            3,
            ["verb-te"],
            {
                "model_provider": None,
                "model_name": None,
                "prompt_version": "companion-turn-v1",
                "attempted_providers": [],
                # A freely typed question carries no angle (§5.15).
                "lens": None,
                "lens_prompt_version": None,
            },
        )
    ]


class RoleTraceRepository:
    def __init__(self) -> None:
        self.traces: list[dict[str, Any]] = []

    def record_role_preview_trace(self, **values: Any) -> None:
        self.traces.append(values)


def test_role_catalogue_and_single_preview_keep_identity_server_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = RoleTraceRepository()

    class RoleLLM:
        def reply_with_metadata(self, messages: list[dict[str, str]], **values: Any) -> LLMReply:
            return LLMReply(
                content=(
                    '{"headline_zh":"当前关系里稍显生硬。","analysis_zh":"同事闲聊时可以更短。",'
                    '"reusable_ja":"そうなんですね。","claim_type":"usage_tendency",'
                    '"focus_tags":["naturalness","register"],"uncertainty_zh":null}'
                ),
                provider="deepseek",
                model="deepseek-v4-flash",
                attempted_providers=("dashscope", "deepseek"),
            )

    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "llm_service", lambda: RoleLLM())

    profiles = main.list_roles()
    result = main.preview_role_perspective(
        "aoi",
        main.RolePreviewRequest(
            sentence_ja="昨日、映画を見る。",
            question="这句话听起来如何？",
            context_zh="和同事闲聊昨天做的事。",
        ),
    )

    assert len(profiles) == 4
    assert profiles[0]["role_type"] == "host"
    assert all(profile["is_fictional"] for profile in profiles)
    assert result["role"]["id"] == "aoi"
    assert result["perspective"]["claim_type"] == "usage_tendency"
    assert "model_provider" not in result["perspective"]
    assert repository.traces == [
        {
            "role_id": "aoi",
            "manifest_version": "role-manifest-v1",
            "status": "ok",
            "reason": "单角色预览生成成功",
            "duration_ms": repository.traces[0]["duration_ms"],
            "decision_context": {
                "model_provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "prompt_version": "role-perspective-v2",
                "manifest_version": "role-manifest-v1",
                "attempted_providers": ["dashscope", "deepseek"],
                "repair_used": False,
                "generation_calls": 1,
            },
            # repair_used reaches the trace so a blind run can report how often the
            # role held its own lens without the server pulling it back (§5.14).
            "detail": {
                "claim_type": "usage_tendency",
                "focus_tags": ["naturalness", "register"],
                "attempted_providers": ["dashscope", "deepseek"],
                "repair_used": False,
                "generation_calls": 1,
            },
        }
    ]


def test_role_preview_rejects_unknown_role_and_keeps_host_for_m3() -> None:
    payload = main.RolePreviewRequest(sentence_ja="雨です。", question="怎么理解？")

    with pytest.raises(HTTPException) as missing:
        main.preview_role_perspective("missing", payload)
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as host:
        main.preview_role_perspective("haru", payload)
    assert host.value.status_code == 409
    assert "M3" in host.value.detail


def test_invalid_role_contract_is_traced_without_writing_a_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = RoleTraceRepository()

    class BrokenRoleLLM:
        def __init__(self) -> None:
            self.responses = iter(
                [
                    LLMReply("bad", "dashscope", "qwen3.7-max", ("dashscope",)),
                    LLMReply("still bad", "deepseek", "deepseek-v4-flash", ("deepseek",)),
                ]
            )

        def reply_with_metadata(self, messages: list[dict[str, str]], **values: Any) -> LLMReply:
            return next(self.responses)

    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "llm_service", lambda: BrokenRoleLLM())

    with pytest.raises(HTTPException) as caught:
        main.preview_role_perspective(
            "kei",
            main.RolePreviewRequest(sentence_ja="本を読むています。", question="结构有什么问题？"),
        )

    assert caught.value.status_code == 502
    assert repository.traces[0]["status"] == "failed"
    assert repository.traces[0]["failure_stage"] == "parse_contract"
    assert repository.traces[0]["manifest_version"] == "role-manifest-v1"
    assert repository.traces[0]["decision_context"]["model_provider"] == "deepseek"


def test_role_model_failure_is_attributed_without_touching_other_learning_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = RoleTraceRepository()

    class UnavailableRoleLLM:
        def reply_with_metadata(self, messages: list[dict[str, str]], **values: Any) -> LLMReply:
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "llm_service", lambda: UnavailableRoleLLM())

    with pytest.raises(HTTPException) as caught:
        main.preview_role_perspective(
            "lin",
            main.RolePreviewRequest(sentence_ja="随時連絡してください。", question="和中文有什么差异？"),
        )

    assert caught.value.status_code == 503
    assert repository.traces[0]["status"] == "failed"
    assert repository.traces[0]["failure_stage"] == "model_call"
    assert repository.traces[0]["decision_context"] == {"prompt_version": "role-perspective-v2"}


def test_dictionary_prompt_ranks_the_chinese_difference_first() -> None:
    # ① same-form-different-use, ② kanji composition, ③ everything else — in that order,
    # because the first two are the only angles that give a Chinese native both a hook
    # and the reason behind it.
    prompt = main._DICTIONARY_SYSTEM
    assert "中文母语" in prompt
    first = prompt.index("与中文同形但语感")
    second = prompt.index("拆解汉字各自的含义")
    third = prompt.index("再给语感、常见搭配")
    assert first < second < third
    assert "不要为了套用①而牵强附会" in prompt
    # The lookup is no longer clipboard-driven.
    assert "剪贴板" not in prompt
