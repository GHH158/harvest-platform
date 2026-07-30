from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import oss2

from .config import Settings


class ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def upload_audio(self, local_path: Path, oss_key: str) -> str:
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
        bucket = oss2.Bucket(auth, self.settings.oss_endpoint, self.settings.oss_bucket)
        result = bucket.put_object_from_file(oss_key, str(local_path))
        if result.status != 200:
            raise RuntimeError(f"OSS 上传失败，HTTP {result.status}")
        return self.public_url(oss_key)

    def public_url(self, oss_key: str) -> str:
        assert self.settings.oss_public_base_url
        return f"{self.settings.oss_public_base_url.rstrip('/')}/{quote(oss_key)}"
