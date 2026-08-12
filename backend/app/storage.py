from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from urllib.parse import quote

import oss2
from oss2.models import BucketLifecycle, LifecycleExpiration, LifecycleRule

from .config import Settings

MULTIPART_THRESHOLD_BYTES = 8 * 1024 * 1024
MULTIPART_PART_SIZE_BYTES = 4 * 1024 * 1024


class ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._bucket_instance: oss2.Bucket | None = None

    def validate_configuration(self) -> None:
        required = {
            "OSS_ENDPOINT": self.settings.oss_endpoint,
            "OSS_BUCKET": self.settings.oss_bucket,
            "OSS_ACCESS_KEY_ID": self.settings.oss_access_key_id,
            "OSS_ACCESS_KEY_SECRET": self.settings.oss_access_key_secret,
            "OSS_PUBLIC_BASE_URL": self.settings.oss_public_base_url,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"OSS 配置不完整: {', '.join(missing)}")

    def _bucket(self) -> oss2.Bucket:
        if self._bucket_instance is not None:
            return self._bucket_instance
        self.validate_configuration()
        auth = oss2.Auth(self.settings.oss_access_key_id, self.settings.oss_access_key_secret)
        self._bucket_instance = oss2.Bucket(
            auth,
            self.settings.oss_endpoint,
            self.settings.oss_bucket,
            connect_timeout=self.settings.oss_upload_timeout_seconds,
        )
        return self._bucket_instance

    def upload_file(self, local_path: Path, oss_key: str) -> str:
        content_type = {
            ".m3u8": "application/vnd.apple.mpegurl",
            ".ts": "video/mp2t",
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".mp4": "video/mp4",
        }.get(local_path.suffix.lower()) or mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        headers = {"Content-Type": content_type}
        last_error: Exception | None = None
        for attempt in range(1, self.settings.oss_upload_max_attempts + 1):
            try:
                result = self._upload_once(local_path, oss_key, headers)
                if result.status != 200:
                    raise RuntimeError(f"OSS 上传失败，HTTP {result.status}")
                break
            except Exception as error:
                if not self._is_retryable(error) or attempt >= self.settings.oss_upload_max_attempts:
                    raise
                last_error = error
                self._bucket_instance = None
                delay = min(2 ** (attempt - 1), 8)
                print(
                    f"OSS 上传暂时失败，{delay} 秒后重试 {attempt + 1}/"
                    f"{self.settings.oss_upload_max_attempts}: {oss_key}: {error}",
                    flush=True,
                )
                time.sleep(delay)
        else:  # pragma: no cover - loop either succeeds or raises.
            assert last_error is not None
            raise last_error
        return self.public_url(oss_key)

    def _upload_once(self, local_path: Path, oss_key: str, headers: dict[str, str]):
        bucket = self._bucket()
        if local_path.stat().st_size < MULTIPART_THRESHOLD_BYTES:
            return bucket.put_object_from_file(oss_key, str(local_path), headers=headers)
        checkpoint_root = self.settings.data_dir / "oss-upload-checkpoints"
        checkpoint_root.mkdir(parents=True, exist_ok=True)
        return oss2.resumable_upload(
            bucket,
            oss_key,
            str(local_path),
            store=oss2.ResumableStore(root=str(checkpoint_root)),
            headers=headers,
            multipart_threshold=MULTIPART_THRESHOLD_BYTES,
            part_size=MULTIPART_PART_SIZE_BYTES,
            num_threads=1,
        )

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        if isinstance(error, oss2.exceptions.RequestError):
            return True
        if isinstance(error, oss2.exceptions.ServerError):
            return int(error.status) in {408, 429, 500, 502, 503, 504}
        return False

    def upload_audio(self, local_path: Path, oss_key: str) -> str:
        return self.upload_file(local_path, oss_key)

    def upload_tree(self, directory: Path, oss_prefix: str) -> list[str]:
        files = sorted(
            (path for path in directory.rglob("*") if path.is_file()),
            key=lambda path: (path.suffix.lower() == ".m3u8", path.as_posix()),
        )
        if not files:
            raise RuntimeError(f"没有可上传的 HLS 文件: {directory}")
        remote_sizes = self._remote_sizes(f"{oss_prefix.rstrip('/')}/")
        keys: list[str] = []
        for path in files:
            relative = path.relative_to(directory).as_posix()
            key = f"{oss_prefix.rstrip('/')}/{relative}"
            if remote_sizes.get(key) != path.stat().st_size:
                self.upload_file(path, key)
            keys.append(key)
        return keys

    def _remote_sizes(self, prefix: str) -> dict[str, int]:
        try:
            return {
                item.key: int(item.size)
                for item in oss2.ObjectIterator(self._bucket(), prefix=prefix)
            }
        except (oss2.exceptions.RequestError, oss2.exceptions.ServerError):
            # Listing is an optimization. Per-object retries below remain the
            # source of truth if the network is too unstable for this preflight.
            self._bucket_instance = None
            return {}

    def delete(self, oss_key: str) -> None:
        self._bucket().delete_object(oss_key)

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under `prefix`, returning how many were removed.

        §15.7: deleting a material has to clear its cloud objects, and it deliberately
        does NOT swallow failures. An object left behind under a prefix whose database
        row is gone keeps costing storage forever and nothing is left to say who owned
        it — so the delete fails as a whole and can be retried instead.

        Batched because a split collection can hold thousands of HLS segments; OSS caps
        `batch_delete_objects` at 1000 keys per call.
        """

        bucket = self._bucket()
        keys = [item.key for item in oss2.ObjectIterator(bucket, prefix=prefix)]
        for start in range(0, len(keys), 1_000):
            bucket.batch_delete_objects(keys[start : start + 1_000])
        return len(keys)

    def configure_lifecycle(self) -> list[dict[str, int | str]]:
        """Merge Harvest cleanup rules without replacing unrelated bucket rules."""
        bucket = self._bucket()
        try:
            existing_rules = list(bucket.get_bucket_lifecycle().rules)
        except oss2.exceptions.NoSuchLifecycle:
            existing_rules = []

        harvest_rules = [
            LifecycleRule(
                "harvest-temporary-asr",
                "temporary/",
                expiration=LifecycleExpiration(days=self.settings.oss_temporary_retention_days),
            ),
            LifecycleRule(
                "harvest-shadowing-recordings",
                "shadowing/",
                expiration=LifecycleExpiration(days=self.settings.oss_shadowing_retention_days),
            ),
        ]
        harvest_ids = {rule.id for rule in harvest_rules}
        merged_rules = [rule for rule in existing_rules if rule.id not in harvest_ids] + harvest_rules
        result = bucket.put_bucket_lifecycle(BucketLifecycle(merged_rules))
        if result.status != 200:
            raise RuntimeError(f"OSS 生命周期规则保存失败，HTTP {result.status}")
        return [
            {"id": rule.id, "prefix": rule.prefix, "days": int(rule.expiration.days)}
            for rule in harvest_rules
        ]

    def public_url(self, oss_key: str) -> str:
        self.validate_configuration()
        assert self.settings.oss_public_base_url  # Narrowed by validate_configuration.
        return f"{self.settings.oss_public_base_url.rstrip('/')}/{quote(oss_key)}"

    #: §15.11 补记(2026-08-12): both sides used to stay silent about `Content-Type`
    #: instead of agreeing on one — real-device evidence (a 1h52m video, genuine
    #: `SignatureDoesNotMatch`) showed that contract does not hold for large uploads.
    #: iOS's `URLSession` has documented cases of attaching a `Content-Type` on large
    #: file uploads that the caller never set explicitly; silence on the signing side
    #: cannot defend against a header appearing on the sending side that neither side
    #: chose. Pinning both sides to the same explicit value removes the ambiguity
    #: instead of relying on both staying quiet.
    OSS_UPLOAD_CONTENT_TYPE = "application/octet-stream"

    def presigned_put_url(self, oss_key: str, *, expires_in: int) -> str:
        """A URL the phone can `PUT` a raw file to directly, bypassing the Mac (§15.11).

        Signed with an explicit `Content-Type` (see `OSS_UPLOAD_CONTENT_TYPE`) that the
        phone's `PUT` must send verbatim — both sides agree on the same value rather
        than both trying to omit it.
        """

        self.validate_configuration()
        headers = {"Content-Type": self.OSS_UPLOAD_CONTENT_TYPE}
        return self._bucket().sign_url("PUT", oss_key, expires_in, headers=headers)

    def object_size(self, oss_key: str) -> int:
        """How big the object at `oss_key` actually is, straight from OSS.

        Called before `download_to_file` (§15.11): a direct multipart upload is checked
        against `max_video_upload_bytes` while it streams in, but a phone that went
        through OSS instead skips that check entirely — this is where it happens instead,
        before the Mac spends any bandwidth or disk pulling the object down.
        """

        self.validate_configuration()
        return int(self._bucket().head_object(oss_key).content_length)

    def download_to_file(self, oss_key: str, destination: Path) -> None:
        """Pull an object down to local disk, with the same retry policy as uploads.

        The Mac's own downlink is doing this, not the phone's uplink — that asymmetry is
        the entire point of §15.11: a residential connection's upload side is usually the
        weak one, and OSS's ingress from a mobile network is usually much stronger than a
        home connection's ingress from Tailscale.
        """

        last_error: Exception | None = None
        for attempt in range(1, self.settings.oss_upload_max_attempts + 1):
            try:
                self._bucket().get_object_to_file(oss_key, str(destination))
                return
            except Exception as error:
                if not self._is_retryable(error) or attempt >= self.settings.oss_upload_max_attempts:
                    raise
                last_error = error
                self._bucket_instance = None
                delay = min(2 ** (attempt - 1), 8)
                print(
                    f"OSS 下载暂时失败，{delay} 秒后重试 {attempt + 1}/"
                    f"{self.settings.oss_upload_max_attempts}: {oss_key}: {error}",
                    flush=True,
                )
                time.sleep(delay)
        assert last_error is not None  # pragma: no cover - loop either returns or raises.
        raise last_error
