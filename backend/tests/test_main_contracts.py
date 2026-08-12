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


def test_section_being_cut_does_not_promise_three_minutes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Real payload from 2026-08-12: section 54 of a 1h52m cut reported
    `progress_label: "正在准备素材"` with `eta_minutes: 3`, while what it was actually
    waiting for was a 27-minute encode. A section has no job of its own to describe (the
    cut is one collection-level `split_video` job with `material_id = NULL`), so it fell
    through to the generic default. Saying "3 分钟" to someone watching nothing move for
    twelve is worse than saying nothing.
    """

    monkeypatch.setattr(main, "get_settings", lambda: Settings(data_dir=tmp_path))
    section = main.serialise_material(
        {
            "id": 54,
            "status": "pending",
            "collection_id": 6,
            "error_message": None,
            "audio_oss_key": None,
            "video_oss_key": None,
            "thumbnail_local_path": None,
            "current_job_id": None,
            "current_job_kind": None,
            "current_job_status": None,
            "current_job_error_message": None,
            "current_job_payload": None,
            "current_job_updated_at": None,
        }
    )
    assert section["progress_label"] == "正在切这一节"
    assert section["eta_minutes"] is None, "切分没有可知的 ETA，不许编一个"

    # Already cut (duration_ms present) but its job row is gone — a section whose job was
    # cascade-deleted must not go on claiming to be mid-cut.
    orphaned = main.serialise_material(
        {
            "id": 59,
            "status": "processing",
            "collection_id": 6,
            "duration_ms": 1_642_987,
            "error_message": None,
            "audio_oss_key": None,
            "video_oss_key": None,
            "thumbnail_local_path": None,
            "current_job_id": None,
            "current_job_kind": None,
            "current_job_status": None,
            "current_job_error_message": None,
            "current_job_payload": None,
            "current_job_updated_at": None,
        }
    )
    assert orphaned["progress_label"] != "正在切这一节"

    # Once 转录 is tapped the section does own a job, and that job's real label must win.
    transcribing = main.serialise_material(
        {
            "id": 54,
            "status": "processing",
            "collection_id": 6,
            "error_message": None,
            "audio_oss_key": None,
            "video_oss_key": None,
            "thumbnail_local_path": None,
            "current_job_id": 101,
            "current_job_kind": "upload_video",
            "current_job_status": "running",
            "current_job_payload": {},
            "current_job_error_message": None,
            "current_job_updated_at": datetime.now(UTC),
        }
    )
    assert transcribing["progress_label"] == "正在上传媒体"


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


class ReadingQuestionRepository:
    """§16: a word/phrase/sentence flagged while reading, worked through later."""

    def __init__(self, *, material_exists: bool = True) -> None:
        self.material_exists = material_exists
        self.rows: dict[int, dict[str, Any]] = {}
        self.next_id = 1

    def get_material(self, material_id: int) -> dict[str, Any] | None:
        return {"id": material_id} if self.material_exists else None

    def add_reading_question(
        self, *, material_id: int, excerpt: str, segment_id: int | None = None, note: str | None = None
    ) -> dict[str, Any]:
        row = {
            "id": self.next_id,
            "material_id": material_id,
            "segment_id": segment_id,
            "excerpt": excerpt,
            "note": note,
            "status": "pending",
            "archived_at": None,
        }
        self.rows[self.next_id] = row
        self.next_id += 1
        return row

    def reading_questions(self, material_id: int, *, status: str | None = None) -> list[dict[str, Any]]:
        return [
            row
            for row in self.rows.values()
            if row["material_id"] == material_id and (status is None or row["status"] == status)
        ]

    def set_reading_question_note(self, question_id: int, note: str) -> dict[str, Any] | None:
        row = self.rows.get(question_id)
        if row is None:
            return None
        row["note"] = note
        return row

    def set_reading_question_archived(self, question_id: int, archived: bool) -> dict[str, Any] | None:
        row = self.rows.get(question_id)
        if row is None:
            return None
        row["status"] = "archived" if archived else "pending"
        row["archived_at"] = "now" if archived else None
        return row

    def delete_reading_question(self, question_id: int) -> bool:
        return self.rows.pop(question_id, None) is not None


def test_reading_question_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = ReadingQuestionRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)

    created = main.post_reading_question(
        7, main.ReadingQuestionCreate(excerpt="せっかく", note="  跟中文难得感觉不一样  ")
    )
    assert created["excerpt"] == "せっかく"
    assert created["note"] == "跟中文难得感觉不一样"
    assert created["status"] == "pending"

    listed = main.get_reading_questions(7, status_filter=None)
    assert [item["id"] for item in listed] == [created["id"]]

    noted = main.patch_reading_question_note(created["id"], main.ReadingQuestionNoteUpdate(note="改一下备注"))
    assert noted["note"] == "改一下备注"

    archived = main.patch_reading_question_archive(created["id"], main.ReadingQuestionArchiveUpdate(archived=True))
    assert archived["status"] == "archived"
    assert archived["archived_at"] is not None

    # Archiving is reversible — it is a checkbox, not a one-way trapdoor.
    unarchived = main.patch_reading_question_archive(
        created["id"], main.ReadingQuestionArchiveUpdate(archived=False)
    )
    assert unarchived["status"] == "pending"
    assert unarchived["archived_at"] is None

    main.delete_reading_question(created["id"])
    assert main.get_reading_questions(7, status_filter=None) == []


def test_reading_question_create_rejects_unknown_material(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = ReadingQuestionRepository(material_exists=False)
    monkeypatch.setattr(main, "repository", lambda: repository)

    with pytest.raises(HTTPException) as caught:
        main.post_reading_question(99, main.ReadingQuestionCreate(excerpt="せっかく"))
    assert caught.value.status_code == 404


def test_reading_question_list_rejects_an_invalid_status_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = ReadingQuestionRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)

    with pytest.raises(HTTPException) as caught:
        main.get_reading_questions(7, status_filter="done")
    assert caught.value.status_code == 422


def test_reading_question_note_and_archive_and_delete_404_on_unknown_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = ReadingQuestionRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)

    with pytest.raises(HTTPException) as caught:
        main.patch_reading_question_note(999, main.ReadingQuestionNoteUpdate(note="x"))
    assert caught.value.status_code == 404

    with pytest.raises(HTTPException) as caught:
        main.patch_reading_question_archive(999, main.ReadingQuestionArchiveUpdate(archived=True))
    assert caught.value.status_code == 404

    with pytest.raises(HTTPException) as caught:
        main.delete_reading_question(999)
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


class RecordingOSSPresignStorage:
    """Stands in for `ObjectStorage` in the §15.11 endpoint tests below."""

    last_instance: RecordingOSSPresignStorage | None = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.signed: tuple[str, int] | None = None
        RecordingOSSPresignStorage.last_instance = self

    def presigned_put_url(self, oss_key: str, *, expires_in: int) -> str:
        self.signed = (oss_key, expires_in)
        return f"https://example-oss.aliyuncs.com/{oss_key}?signed=1"


def test_upload_probe_accepts_a_small_body_and_returns_no_content() -> None:
    # §15.11: the phone times exactly this call to decide whether the direct-to-Mac
    # upload path is fast enough, or whether to go through OSS instead.
    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"x" * 1_000, "more_body": False}

    request = Request({"type": "http", "method": "PUT", "path": "/videos/uploads/probe", "headers": []}, receive)

    response = asyncio.run(main.put_upload_probe(request))

    assert response.status_code == 204


def test_upload_probe_rejects_a_payload_larger_than_the_probe_itself() -> None:
    # A confused client sending something big here would otherwise measure the Mac's
    # throughput honestly but cost real bandwidth doing it — reject before reading it all.
    async def receive() -> dict[str, Any]:
        return {
            "type": "http.request",
            "body": b"x" * (main.UPLOAD_PROBE_MAX_BYTES + 1),
            "more_body": False,
        }

    request = Request({"type": "http", "method": "PUT", "path": "/videos/uploads/probe", "headers": []}, receive)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(main.put_upload_probe(request))
    assert caught.value.status_code == 413


def test_oss_upload_url_signs_a_temporary_raw_uploads_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "ObjectStorage", RecordingOSSPresignStorage)
    monkeypatch.setattr(main, "get_settings", lambda: Settings())

    result = main.post_oss_upload_url(main.OSSUploadURLRequest(filename="下载的HLS.zip"))

    assert result["oss_key"].startswith("temporary/raw-uploads/")
    assert result["oss_key"].endswith(".zip")
    assert result["upload_url"] == f"https://example-oss.aliyuncs.com/{result['oss_key']}?signed=1"
    assert RecordingOSSPresignStorage.last_instance is not None
    assert RecordingOSSPresignStorage.last_instance.signed == (result["oss_key"], result["expires_in"])


def test_oss_upload_url_rejects_a_bare_playlist_with_the_same_friendly_message() -> None:
    # Same rule as `POST /videos/uploads` (§15.10): a lone `.m3u8` is useless without its
    # segments, and this endpoint never even sees the file to tell the two cases apart —
    # it only has the filename, so the message has to be filename-driven too.
    with pytest.raises(HTTPException) as caught:
        main.post_oss_upload_url(main.OSSUploadURLRequest(filename="play.m3u8"))
    assert caught.value.status_code == 415
    assert "单独传它没用" in caught.value.detail


def test_video_upload_from_oss_rejects_a_key_outside_the_expected_prefix() -> None:
    # `oss_key` arrives from the client; accepting an arbitrary key would let it point
    # `fetch_video_upload` at any object in the bucket, not just one this service issued.
    with pytest.raises(HTTPException) as caught:
        main.post_video_upload_from_oss(
            main.OSSUploadNotify(oss_key="materials/7/hls/video/index.m3u8", filename="v.mp4")
        )
    assert caught.value.status_code == 422


def test_video_upload_from_oss_enqueues_a_fetch_job(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = StandaloneJobRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)

    result = main.post_video_upload_from_oss(
        main.OSSUploadNotify(oss_key="temporary/raw-uploads/abc123.zip", filename="下载的HLS.zip")
    )

    assert result == {"job_id": 91, "status": "pending"}
    assert repository.enqueued == {
        "kind": "fetch_video_upload",
        "material_id": None,
        "payload": {"oss_key": "temporary/raw-uploads/abc123.zip", "filename": "下载的HLS.zip"},
    }


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
