import zipfile
from pathlib import Path

import pytest
from app.config import Settings
from app.repository import Job
from app.worker import Worker, extract_article_html


def test_readability_extractor_prefers_article_content() -> None:
    html = """
    <html>
      <head><title>雨の日の散歩</title></head>
      <body>
        <nav>広告とメニュー</nav>
        <article>
          <h1>雨の日の散歩</h1>
          <p>雨の日は、ゆっくり歩くのが好きです。</p>
          <p>傘の音を聞きながら、街を見ます。</p>
        </article>
        <footer>Copyright</footer>
      </body>
    </html>
    """

    title, article = extract_article_html(html, "https://example.com/rain")

    assert title == "雨の日の散歩"
    assert "雨の日は、ゆっくり歩くのが好きです。" in article
    assert "広告とメニュー" not in article


class RecordingRepository:
    def __init__(self) -> None:
        self.updated_title: tuple[int, str] | None = None
        self.enqueued: dict | None = None

    def update_material_title(self, material_id: int, title: str) -> None:
        self.updated_title = material_id, title

    def enqueue_job(self, *, kind: str, material_id: int, payload: dict) -> int:
        self.enqueued = {"kind": kind, "material_id": material_id, "payload": payload}
        return 1


def test_url_fetch_uses_page_title_when_user_did_not_provide_one(monkeypatch) -> None:
    repository = RecordingRepository()
    worker = Worker(repository, Settings())
    monkeypatch.setattr("app.worker.extract_article", lambda _: ("雨の日の散歩", "雨です。"))

    worker._fetch(Job(id=1, kind="fetch", material_id=8, payload={"url": "https://example.com"}, attempts=1))

    assert repository.updated_title == (8, "雨の日の散歩")
    assert repository.enqueued == {
        "kind": "tts",
        "material_id": 8,
        "payload": {"text": "雨です。"},
    }


def test_url_fetch_keeps_a_user_supplied_title(monkeypatch) -> None:
    repository = RecordingRepository()
    worker = Worker(repository, Settings())
    monkeypatch.setattr("app.worker.extract_article", lambda _: ("ページの題", "雨です。"))

    worker._fetch(
        Job(
            id=1,
            kind="fetch",
            material_id=8,
            payload={"url": "https://example.com", "title_provided": True},
            attempts=1,
        )
    )

    assert repository.updated_title is None


# --- §15.11: fetching a raw upload back from OSS when the phone chose that path ---


class FetchUploadRepository:
    def __init__(self) -> None:
        self.merged: tuple[int, dict] | None = None

    def merge_job_payload(self, job_id: int, values: dict) -> None:
        self.merged = (job_id, values)


class RecordingFetchStorage:
    def __init__(self, size: int, written: bytes) -> None:
        self.size = size
        self.written = written
        self.downloaded: tuple[str, str] | None = None
        self.deleted: str | None = None
        self.validated = False

    def validate_configuration(self) -> None:
        self.validated = True

    def object_size(self, oss_key: str) -> int:
        return self.size

    def download_to_file(self, oss_key: str, destination: Path) -> None:
        self.downloaded = (oss_key, str(destination))
        destination.write_bytes(self.written)

    def delete(self, oss_key: str) -> None:
        self.deleted = oss_key


def test_fetch_video_upload_unpacks_a_zip_bundle_and_records_the_upload_id(tmp_path: Path) -> None:
    archive_bytes_path = tmp_path / "source-for-bytes.zip"
    with zipfile.ZipFile(archive_bytes_path, "w") as bundle:
        bundle.writestr("play", "#EXTM3U\n#EXTINF:6,\nTZhO-00000\n#EXT-X-ENDLIST\n")
        bundle.writestr("TZhO-00000", "segment-bytes")
    zip_bytes = archive_bytes_path.read_bytes()

    repository = FetchUploadRepository()
    worker = Worker(repository, Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    worker.storage = RecordingFetchStorage(size=len(zip_bytes), written=zip_bytes)

    worker._fetch_video_upload(
        Job(
            id=5,
            kind="fetch_video_upload",
            material_id=None,
            payload={"oss_key": "temporary/raw-uploads/abc.zip", "filename": "下载的HLS.zip"},
            attempts=1,
        )
    )

    assert worker.storage.validated
    assert worker.storage.downloaded[0] == "temporary/raw-uploads/abc.zip"
    assert worker.storage.deleted == "temporary/raw-uploads/abc.zip"
    assert repository.merged is not None
    job_id, values = repository.merged
    assert job_id == 5
    assert values["filename"] == "下载的HLS.zip"
    video_dir = tmp_path / "video" / "uploads"
    upload_id = Path(values["upload_id"])
    assert (video_dir / upload_id).exists()
    assert (video_dir / upload_id).read_text(encoding="utf-8").startswith("#EXTM3U")
    # The zip itself is gone once unpacked — only the extracted folder remains.
    assert not list(video_dir.glob("pending-*.zip"))


def test_fetch_video_upload_keeps_a_plain_video_file_as_is(tmp_path: Path) -> None:
    repository = FetchUploadRepository()
    worker = Worker(repository, Settings(data_dir=tmp_path, min_free_disk_bytes=0))
    worker.storage = RecordingFetchStorage(size=4, written=b"1234")

    worker._fetch_video_upload(
        Job(
            id=6,
            kind="fetch_video_upload",
            material_id=None,
            payload={"oss_key": "temporary/raw-uploads/abc.mp4", "filename": "旅行.mp4"},
            attempts=1,
        )
    )

    _, values = repository.merged
    video_dir = tmp_path / "video" / "uploads"
    saved = video_dir / values["upload_id"]
    assert saved.exists()
    assert saved.read_bytes() == b"1234"
    assert saved.name.startswith("pending-") and saved.suffix == ".mp4"


def test_fetch_video_upload_rejects_an_oversized_object_without_downloading_it(tmp_path: Path) -> None:
    repository = FetchUploadRepository()
    worker = Worker(
        repository,
        Settings(data_dir=tmp_path, min_free_disk_bytes=0, max_video_upload_bytes=100),
    )
    storage = RecordingFetchStorage(size=200, written=b"x" * 200)
    worker.storage = storage

    with pytest.raises(RuntimeError, match="太大"):
        worker._fetch_video_upload(
            Job(
                id=7,
                kind="fetch_video_upload",
                material_id=None,
                payload={"oss_key": "temporary/raw-uploads/big.mp4", "filename": "big.mp4"},
                attempts=1,
            )
        )

    assert storage.downloaded is None
    assert storage.deleted == "temporary/raw-uploads/big.mp4"
    assert repository.merged is None


def test_fetch_video_upload_rejects_a_job_missing_source_info(tmp_path: Path) -> None:
    worker = Worker(FetchUploadRepository(), Settings(data_dir=tmp_path, min_free_disk_bytes=0))

    with pytest.raises(RuntimeError, match="缺少来源信息"):
        worker._fetch_video_upload(
            Job(id=8, kind="fetch_video_upload", material_id=None, payload={}, attempts=1)
        )
