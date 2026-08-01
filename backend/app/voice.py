from __future__ import annotations

import re

import httpx

from .config import Settings


def validate_voice_sample_duration(duration_ms: int) -> None:
    if duration_ms < 3_000 or duration_ms > 30_000:
        raise RuntimeError("声音复刻参考录音必须在 3–30 秒之间。")


class VoiceEnrollmentService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_japanese_voice(self, *, audio_url: str, prefix: str) -> str:
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY 尚未配置；声音复刻不会在未配置时调用云端。")
        normalized = re.sub(r"[^A-Za-z0-9]", "", prefix)[:10]
        if not normalized:
            raise RuntimeError("音色前缀至少需要一个英文字母或数字。")
        endpoint = f"{self.settings.dashscope_base_url.rstrip('/')}/services/audio/tts/customization"
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {self.settings.dashscope_api_key}"},
            json={
                "model": "voice-enrollment",
                "input": {
                    "action": "create_voice",
                    "target_model": self.settings.dashscope_tts_model,
                    "prefix": normalized,
                    "url": audio_url,
                    "language_hints": ["ja"],
                    "max_prompt_audio_length": 30,
                    "enable_preprocess": True,
                },
            },
            timeout=180.0,
        )
        response.raise_for_status()
        voice_id = response.json().get("output", {}).get("voice_id")
        if not isinstance(voice_id, str) or not voice_id.strip():
            raise RuntimeError("百炼声音复刻没有返回 voice_id。")
        return voice_id.strip()
