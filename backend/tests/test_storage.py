from pathlib import Path
from types import SimpleNamespace

import oss2
import pytest
from app.config import Settings
from app.storage import ObjectStorage
from oss2.models import LifecycleExpiration, LifecycleRule


class RecordingBucket:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, dict[str, str]]] = []

    def put_object_from_file(self, key: str, path: str, headers: dict[str, str]) -> SimpleNamespace:
        self.uploads.append((key, path, headers))
        return SimpleNamespace(status=200)

    def list_objects(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(
            object_list=[],
            prefix_list=[],
            is_truncated=False,
            next_marker="",
        )


def test_hls_tree_upload_uses_apple_media_types(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "index.m3u8").write_text("#EXTM3U\n")
    (tmp_path / "segment-00000.ts").write_bytes(b"segment")
    bucket = RecordingBucket()
    storage = ObjectStorage(
        Settings(
            oss_endpoint="https://oss-cn-beijing.aliyuncs.com",
            oss_bucket="harvest-test",
            oss_access_key_id="id",
            oss_access_key_secret="secret",
            oss_public_base_url="https://media.example",
        )
    )
    monkeypatch.setattr(storage, "_bucket", lambda: bucket)

    keys = storage.upload_tree(tmp_path, "materials/7/hls/video")

    assert keys == [
        "materials/7/hls/video/segment-00000.ts",
        "materials/7/hls/video/index.m3u8",
    ]
    assert [item[2]["Content-Type"] for item in bucket.uploads] == [
        "video/mp2t",
        "application/vnd.apple.mpegurl",
    ]


def test_upload_retries_a_transient_request_error(monkeypatch, tmp_path: Path) -> None:
    sample = tmp_path / "sample.m4a"
    sample.write_bytes(b"audio")

    class FlakyBucket(RecordingBucket):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def put_object_from_file(self, key: str, path: str, headers: dict[str, str]) -> SimpleNamespace:
            self.attempts += 1
            if self.attempts == 1:
                raise oss2.exceptions.RequestError(TimeoutError("timed out"))
            return super().put_object_from_file(key, path, headers)

    bucket = FlakyBucket()
    storage = ObjectStorage(
        Settings(
            oss_endpoint="https://oss-cn-beijing.aliyuncs.com",
            oss_bucket="harvest-test",
            oss_access_key_id="id",
            oss_access_key_secret="secret",
            oss_public_base_url="https://media.example",
            oss_upload_max_attempts=2,
        )
    )
    monkeypatch.setattr(storage, "_bucket", lambda: bucket)
    monkeypatch.setattr("app.storage.time.sleep", lambda _: None)

    storage.upload_file(sample, "temporary/sample.m4a")

    assert bucket.attempts == 2


def test_hls_retry_skips_matching_remote_segments_but_publishes_playlist_last(
    monkeypatch, tmp_path: Path
) -> None:
    segment = tmp_path / "segment-00000.ts"
    segment.write_bytes(b"existing")
    playlist = tmp_path / "index.m3u8"
    playlist.write_text("#EXTM3U\n")
    bucket = RecordingBucket()
    storage = ObjectStorage(Settings())
    monkeypatch.setattr(storage, "_bucket", lambda: bucket)
    monkeypatch.setattr(
        storage,
        "_remote_sizes",
        lambda _: {"materials/7/hls/video/segment-00000.ts": segment.stat().st_size},
    )

    keys = storage.upload_tree(tmp_path, "materials/7/hls/video")

    assert keys == [
        "materials/7/hls/video/segment-00000.ts",
        "materials/7/hls/video/index.m3u8",
    ]
    assert [item[0] for item in bucket.uploads] == ["materials/7/hls/video/index.m3u8"]


def test_storage_configuration_reports_missing_public_base_url() -> None:
    with pytest.raises(RuntimeError, match="OSS_PUBLIC_BASE_URL"):
        ObjectStorage(
            Settings(
                oss_endpoint="https://oss-cn-beijing.aliyuncs.com",
                oss_bucket="harvest-test",
                oss_access_key_id="id",
                oss_access_key_secret="secret",
                oss_public_base_url=None,
            )
        ).validate_configuration()


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
