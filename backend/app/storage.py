from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

import oss2

from .config import Settings


class ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._bucket_instance: oss2.Bucket | None = None

    def _bucket(self) -> oss2.Bucket:
        if self._bucket_instance is not None:
            return self._bucket_instance
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
        auth = oss2.Auth(self.settings.oss_access_key_id, self.settings.oss_access_key_secret)
        self._bucket_instance = oss2.Bucket(auth, self.settings.oss_endpoint, self.settings.oss_bucket)
        return self._bucket_instance

    def upload_file(self, local_path: Path, oss_key: str) -> str:
        content_type = {
            ".m3u8": "application/vnd.apple.mpegurl",
            ".ts": "video/mp2t",
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".mp4": "video/mp4",
        }.get(local_path.suffix.lower()) or mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        result = self._bucket().put_object_from_file(
            oss_key,
            str(local_path),
            headers={"Content-Type": content_type},
        )
        if result.status != 200:
            raise RuntimeError(f"OSS 上传失败，HTTP {result.status}")
        return self.public_url(oss_key)

    def upload_audio(self, local_path: Path, oss_key: str) -> str:
        return self.upload_file(local_path, oss_key)

    def upload_tree(self, directory: Path, oss_prefix: str) -> list[str]:
        files = sorted(path for path in directory.rglob("*") if path.is_file())
        if not files:
            raise RuntimeError(f"没有可上传的 HLS 文件: {directory}")
        keys: list[str] = []
        for path in files:
            relative = path.relative_to(directory).as_posix()
            key = f"{oss_prefix.rstrip('/')}/{relative}"
            self.upload_file(path, key)
            keys.append(key)
        return keys

    def delete(self, oss_key: str) -> None:
        self._bucket().delete_object(oss_key)

    def public_url(self, oss_key: str) -> str:
        assert self.settings.oss_public_base_url
        return f"{self.settings.oss_public_base_url.rstrip('/')}/{quote(oss_key)}"
