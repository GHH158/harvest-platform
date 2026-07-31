from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.storage import ObjectStorage


class RecordingBucket:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, dict[str, str]]] = []

    def put_object_from_file(self, key: str, path: str, headers: dict[str, str]) -> SimpleNamespace:
        self.uploads.append((key, path, headers))
        return SimpleNamespace(status=200)


def test_hls_tree_upload_uses_apple_media_types(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "index.m3u8").write_text("#EXTM3U\n")
    (tmp_path / "segment-00000.ts").write_bytes(b"segment")
    bucket = RecordingBucket()
    storage = ObjectStorage(Settings(oss_public_base_url="https://media.example"))
    monkeypatch.setattr(storage, "_bucket", lambda: bucket)

    keys = storage.upload_tree(tmp_path, "materials/7/hls/video")

    assert keys == [
        "materials/7/hls/video/index.m3u8",
        "materials/7/hls/video/segment-00000.ts",
    ]
    assert [item[2]["Content-Type"] for item in bucket.uploads] == [
        "application/vnd.apple.mpegurl",
        "video/mp2t",
    ]
