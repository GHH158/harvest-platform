from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import pytest
from app import main
from app.config import Settings
from starlette.requests import Request

_MATERIAL = {
    "id": 1,
    "title": "雨の日の散歩",
    "kind": "reading",
    "source_type": "paste",
    "status": "ready",
    "created_at": datetime.datetime(2026, 8, 1, 12, 30, tzinfo=datetime.UTC),
    "error_message": None,
}

_JOB = {
    "id": 7,
    "kind": "tts",
    "material_id": 1,
    "material_title": "雨の日の散歩",
    "status": "running",
    "attempts": 1,
    "created_at": datetime.datetime(2026, 8, 1, 12, 30, tzinfo=datetime.UTC),
    "error_message": None,
}


class FakeAdminRepository:
    def __init__(self, *, materials: list[dict[str, Any]] | None = None, jobs: list[dict[str, Any]] | None = None) -> None:
        self.materials = materials or []
        self.jobs = jobs or []
        self.material_count = len(self.materials)
        self.job_count = len(self.jobs)
        self.list_material_calls: list[tuple[str | None, int | None, int]] = []
        self.list_job_calls: list[tuple[str | None, str | None, int | None, int]] = []

    def count_materials(self, *, status: str | None = None) -> int:
        return self.material_count

    def list_materials(self, *, status: str | None = None, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        self.list_material_calls.append((status, limit, offset))
        return self.materials

    def count_jobs(self, *, status: str | None = None, kind: str | None = None) -> int:
        return self.job_count

    def list_jobs(
        self, *, status: str | None = None, kind: str | None = None, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        self.list_job_calls.append((status, kind, limit, offset))
        return self.jobs


def request(path: str = "/admin/materials") -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "headers": []})


def test_admin_materials_page_renders_rows_and_sidebar(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeAdminRepository(materials=[_MATERIAL])
    monkeypatch.setattr(main, "repository", lambda: repository)

    response = main.admin_materials_page(request=request(), page=1, limit=50)

    assert response.status_code == 200
    body = response.body.decode()
    assert "雨の日の散歩" in body
    assert "已就绪" in body
    assert 'href="/admin/materials"' in body  # sidebar active item
    assert 'href="/ingest-web"' in body  # sidebar nav rendered


def test_admin_materials_page_empty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeAdminRepository()
    monkeypatch.setattr(main, "repository", lambda: repository)

    response = main.admin_materials_page(request=request(), page=1, limit=50)

    assert response.status_code == 200
    assert "暂无材料" in response.body.decode()


def test_admin_materials_page_pagination_links(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeAdminRepository(materials=[_MATERIAL] * 60)
    monkeypatch.setattr(main, "repository", lambda: repository)

    response = main.admin_materials_page(request=request(), page=1, limit=50)

    body = response.body.decode()
    assert "共 60 条" in body
    assert "下一页" in body  # more than one page
    assert "disabled" in body  # 上一页 disabled on page 1


def test_admin_materials_page_forwards_status_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeAdminRepository(materials=[_MATERIAL])
    monkeypatch.setattr(main, "repository", lambda: repository)

    response = main.admin_materials_page(request=request(), status_filter="ready", page=1, limit=50)

    assert response.status_code == 200
    assert repository.list_material_calls == [("ready", 50, 0)]


def test_admin_jobs_page_renders_rows_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeAdminRepository(jobs=[_JOB])
    monkeypatch.setattr(main, "repository", lambda: repository)

    response = main.admin_jobs_page(request=request("/admin/jobs"), status_filter="running", kind="tts", page=1, limit=50)

    assert response.status_code == 200
    body = response.body.decode()
    assert "执行中" in body
    assert "雨の日の散歩" in body
    assert "重试次数" in body
    assert repository.list_job_calls == [("running", "tts", 50, 0)]


def test_admin_jobs_page_contains_refresh_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeAdminRepository(jobs=[_JOB])
    monkeypatch.setattr(main, "repository", lambda: repository)

    response = main.admin_jobs_page(request=request("/admin/jobs"), page=1, limit=50)

    assert response.status_code == 200
    assert 'http-equiv="refresh"' in response.body.decode()


def test_ingest_page_renders_with_sidebar() -> None:
    response = main.ingest_page(request=request("/ingest-web"))

    assert response.status_code == 200
    body = response.body.decode()
    assert "添加阅读材料" in body
    assert 'href="/admin/materials"' in body
    assert 'href="/settings"' in body


def test_settings_page_renders_with_sidebar_and_badges() -> None:
    response = main.settings_page(request=request("/settings"))

    assert response.status_code == 200
    body = response.body.decode()
    assert "服务设置" in body
    assert 'href="/ingest-web"' in body
    assert "已配置" in body or "未配置" in body  # secret status badges render


def _local_assets(root: Path, material_id: int) -> dict[str, str]:
    base = root / "video" / f"material-{material_id}"
    return {
        "video_directory": str(base / "hls-video"),
        "audio_directory": str(base / "hls-audio"),
        "asr_audio_path": str(base / "asr-audio.m4a"),
    }


class TranscriptionRepository:
    def __init__(
        self,
        material: dict[str, Any] | None,
        transcode_payload: dict[str, Any] | None,
        local_assets: dict[str, str] | None = None,
    ) -> None:
        self.material = material
        self.transcode_payload = transcode_payload
        self.local_assets = local_assets
        self.enqueued: list[tuple[str, int | None, dict[str, Any]]] = []
        self.processed: list[int] = []

    def get_material(self, material_id: int) -> dict[str, Any] | None:
        return self.material

    def latest_transcode_payload(self, material_id: int) -> dict[str, Any] | None:
        return self.transcode_payload

    def local_video_transcription_assets(self, material_id: int) -> dict[str, str] | None:
        return self.local_assets

    def mark_material_processing(self, material_id: int) -> None:
        self.processed.append(material_id)

    def enqueue_job(self, *, kind: str, material_id: int | None, payload: dict[str, Any]) -> int:
        self.enqueued.append((kind, material_id, payload))
        return 1


def test_start_transcription_enqueues_upload_video(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    video = {"id": 7, "kind": "video", "status": "downloaded", "title": "视频"}
    assets = _local_assets(tmp_path, 7)
    repository = TranscriptionRepository(video, {"source_path": "/tmp/source.mp4"}, assets)
    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "get_settings", lambda: Settings(data_dir=tmp_path))

    response = main.start_transcription(7)

    assert response.status_code == 303
    assert repository.processed == [7]
    assert len(repository.enqueued) == 1
    kind, material_id, payload = repository.enqueued[0]
    assert kind == "upload_video"
    assert material_id == 7
    assert payload["source_path"] == "/tmp/source.mp4"
    assert payload["video_directory"] == assets["video_directory"]
    assert payload["audio_directory"] == assets["audio_directory"]
    assert payload["asr_audio_path"] == assets["asr_audio_path"]


def test_split_section_can_start_transcription_without_an_archive_original(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The real 2026-08-12 failure: every section of every split video was untranscribable.

    A section has no `transcode` job of its own (the cut is one collection-level
    `split_video` job with `material_id = NULL`) and no archive original (§15.2 deletes it
    once the cut lands). Keying 转录 off either of those answered 409 forever.
    """

    section = {"id": 52, "kind": "video", "status": "downloaded", "title": "天気の子 第 2 节"}
    assets = _local_assets(tmp_path, 52)
    repository = TranscriptionRepository(section, None, assets)
    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "get_settings", lambda: Settings(data_dir=tmp_path))

    job_id = main.enqueue_video_transcription(52)

    assert job_id == 1
    kind, material_id, payload = repository.enqueued[0]
    assert kind == "upload_video"
    assert material_id == 52
    assert payload["source_path"] is None, "拆分节没有原片，这里必须是 None 而不是让整件事失败"
    assert payload["video_directory"] == assets["video_directory"]


def test_start_transcription_rejects_wrong_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Video but not downloaded → 409
    ready = {"id": 7, "kind": "video", "status": "ready", "title": "视频"}
    repository = TranscriptionRepository(ready, None)
    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "get_settings", lambda: Settings(data_dir=tmp_path))
    with pytest.raises(Exception) as caught:
        main.start_transcription(7)
    assert caught.value.status_code == 409
    assert repository.enqueued == []

    # Downloaded but not a video → 409
    reading = {"id": 8, "kind": "reading", "status": "downloaded", "title": "阅读"}
    repository2 = TranscriptionRepository(reading, None)
    monkeypatch.setattr(main, "repository", lambda: repository2)
    with pytest.raises(Exception) as caught2:
        main.start_transcription(8)
    assert caught2.value.status_code == 409
    assert repository2.enqueued == []

    # Downloaded video whose local HLS is missing → 409. Note the criterion is the local
    # files, not a `transcode` job: a split section has no such job and must still start.
    video = {"id": 9, "kind": "video", "status": "downloaded", "title": "视频"}
    repository3 = TranscriptionRepository(video, None, None)
    monkeypatch.setattr(main, "repository", lambda: repository3)
    with pytest.raises(Exception) as caught3:
        main.start_transcription(9)
    assert caught3.value.status_code == 409
    assert repository3.enqueued == []
