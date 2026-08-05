from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    # System voices currently do not cover Japanese reliably. Keep this empty
    # until a Japanese-capable cloned/base voice has been selected.
    dashscope_tts_voice: str | None = None
    dashscope_asr_model: str = "fun-asr"
    dashscope_asr_poll_seconds: float = 2.0
    dashscope_asr_timeout_seconds: int = 900
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"
    dashscope_chat_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_chat_model: str = "qwen3.7-max"
    llm_provider: str = "auto"
    llm_fallback_on_error: bool = True
    dashscope_omni_model: str = "qwen3.5-omni-flash-realtime"
    dashscope_omni_ws_url: str | None = None
    dashscope_omni_voice: str = "Ethan"
    # Optional session-specific guidance. The formal teaching prompt is fixed in
    # prompts.py and is always prepended by omni.session_update().
    dashscope_omni_instructions: str = ""
    dashscope_vl_model: str = "qwen-vl-plus"
    oss_endpoint: str | None = None
    oss_bucket: str | None = None
    oss_access_key_id: str | None = None
    oss_access_key_secret: str | None = None
    oss_public_base_url: str | None = None
    oss_temporary_retention_days: int = Field(default=1, ge=1)
    oss_shadowing_retention_days: int = Field(default=7, ge=1)
    oss_upload_timeout_seconds: int = Field(default=90, ge=15, le=600)
    oss_upload_max_attempts: int = Field(default=4, ge=1, le=10)
    tailscale_hostname: str | None = None
    worker_poll_seconds: float = 2.0
    worker_stale_running_seconds: int = 900
    worker_max_attempts: int = 3
    max_video_upload_bytes: int = 2_000_000_000
    max_photo_upload_bytes: int = 20_000_000
    max_audio_upload_bytes: int = 25_000_000
    min_free_disk_bytes: int = 5_000_000_000
    video_download_max_height: int = Field(default=720, ge=240, le=2_160)
    video_download_max_fps: int = Field(default=30, ge=15, le=120)
    video_transcode_max_threads: int = Field(default=2, ge=1, le=8)
    data_dir: Path = ROOT_DIR / "backend" / "data"

    @property
    def local_audio_dir(self) -> Path:
        return self.data_dir / "audio"


@lru_cache
def get_settings() -> Settings:
    return Settings()
