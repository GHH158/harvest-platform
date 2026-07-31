from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration. Secrets are read only from the private .env file."""

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://harvest:harvest@127.0.0.1:5432/harvest"
    dashscope_api_key: str | None = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    dashscope_tts_model: str = "qwen-audio-3.0-tts-plus"
    dashscope_tts_voice: str = "longanhuan_v3.6"
    dashscope_asr_model: str = "fun-asr"
    dashscope_asr_poll_seconds: float = 2.0
    dashscope_asr_timeout_seconds: int = 900
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    dashscope_chat_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_chat_model: str = "qwen-plus"
    dashscope_omni_model: str = "qwen3.5-omni-flash-realtime"
    dashscope_vl_model: str = "qwen-vl-plus"
    oss_endpoint: str | None = None
    oss_bucket: str | None = None
    oss_access_key_id: str | None = None
    oss_access_key_secret: str | None = None
    oss_public_base_url: str | None = None
    tailscale_hostname: str | None = None
    worker_poll_seconds: float = 2.0
    worker_stale_running_seconds: int = 900
    worker_max_attempts: int = 3
    max_video_upload_bytes: int = 2_000_000_000
    min_free_disk_bytes: int = 5_000_000_000
    data_dir: Path = ROOT_DIR / "backend" / "data"

    @property
    def local_audio_dir(self) -> Path:
        return self.data_dir / "audio"


@lru_cache
def get_settings() -> Settings:
    return Settings()
