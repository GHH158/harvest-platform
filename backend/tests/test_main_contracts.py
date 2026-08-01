from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app import main
from app.config import Settings
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers
from starlette.requests import Request


class SubmissionRepository:
    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None

    def create_material_with_job(self, **values: Any) -> tuple[int, int]:
        self.created = values
        return 41, 73


class ShadowingRepository:
    submission: tuple[int, str] | None = None

    def get_segment(self, segment_id: int) -> dict[str, int]:
        return {"id": segment_id}

    def create_shadowing_submission(self, segment_id: int, audio_path: str) -> tuple[int, int]:
        self.submission = segment_id, audio_path
        return 51, 82


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


def test_video_link_creates_download_job(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = SubmissionRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)

    result = main.post_video_link(main.VideoLinkCreate(url="https://example.com/watch/1"))

    assert result == {"material_id": 41, "job_id": 73, "status": "pending"}
    assert repository.created is not None
    assert repository.created["kind"] == "video"
    assert repository.created["job_kind"] == "download_video"


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
    main._engine = None
    main._repository = None

    async def exercise() -> None:
        async with main.lifespan(main.app):
            first = main.repository()
            second = main.repository()
            assert first is second
            assert first.engine is engine

    asyncio.run(exercise())

    assert len(calls) == 2
    assert calls[1] is engine
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

    def get_material(self, material_id: int) -> dict[str, Any]:
        return {"id": material_id}

    def segment_context(self, material_id: int, segment_id: int) -> list[dict[str, Any]]:
        return [{"id": segment_id, "idx": 0, "text_ja": "雨です。"}]

    def add_companion_message(
        self, material_id: int, segment_id: int | None, role: str, content: str
    ) -> dict[str, Any]:
        message = {"id": len(self.messages) + 1, "role": role, "content": content, "created_at": "now"}
        self.messages.append(message)
        return message

    def companion_messages(self, material_id: int) -> list[dict[str, Any]]:
        return self.messages


def test_companion_sends_prior_turns_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = CompanionRepository()
    captured: list[dict[str, str]] = []

    class RecordingLLM:
        def __init__(self, settings: Settings) -> None:
            pass

        def reply(self, messages: list[dict[str, str]]) -> str:
            captured.extend(messages)
            return "新的回答"

    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "LLMService", RecordingLLM)

    result = main.post_companion(main.CompanionRequest(material_id=7, segment_id=3, question="现在的问题"))

    assert [item["content"] for item in captured[1:3]] == ["之前的问题", "之前的回答"]
    assert captured[-1]["content"].endswith("问题：现在的问题")
    assert result["assistant"]["content"] == "新的回答"
