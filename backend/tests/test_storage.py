from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.storage import ObjectStorage
from oss2.models import LifecycleExpiration, LifecycleRule


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


class LifecycleRecordingBucket:
    def __init__(self) -> None:
        self.original_rule = LifecycleRule(
            "owner-archive-rule",
            "archive/",
            expiration=LifecycleExpiration(days=90),
        )
        self.saved = None

    def get_bucket_lifecycle(self) -> SimpleNamespace:
        return SimpleNamespace(rules=[self.original_rule])

    def put_bucket_lifecycle(self, lifecycle) -> SimpleNamespace:
        self.saved = lifecycle
        return SimpleNamespace(status=200)


def test_lifecycle_rules_preserve_unrelated_rules_and_never_match_delivery(monkeypatch) -> None:
    bucket = LifecycleRecordingBucket()
    storage = ObjectStorage(
        Settings(oss_temporary_retention_days=1, oss_shadowing_retention_days=7)
    )
    monkeypatch.setattr(storage, "_bucket", lambda: bucket)

    applied = storage.configure_lifecycle()

    assert applied == [
        {"id": "harvest-temporary-asr", "prefix": "temporary/", "days": 1},
        {"id": "harvest-shadowing-recordings", "prefix": "shadowing/", "days": 7},
    ]
    assert bucket.saved is not None
    assert [rule.id for rule in bucket.saved.rules] == [
        "owner-archive-rule",
        "harvest-temporary-asr",
        "harvest-shadowing-recordings",
    ]
    assert all(rule.prefix != "materials/" for rule in bucket.saved.rules[1:])
