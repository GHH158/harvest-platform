from __future__ import annotations

from pathlib import Path

import httpx

from .config import Settings


class TTSService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def synthesize(self, *, text: str, destination: Path, voice: str | None = None) -> None:
        """Request a non-streaming Qwen-Audio TTS file and retain it locally."""
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY 尚未配置；按 PROJECT.md §2.5 注册并配置后再处理任务。")
        selected_voice = (voice or self.settings.dashscope_tts_voice or "").strip()
        if not selected_voice:
            raise RuntimeError("尚未配置支持日语的 TTS 音色；请先在服务设置页创建或选择声音复刻音色。")
        endpoint = f"{self.settings.dashscope_base_url.rstrip('/')}/services/audio/tts/SpeechSynthesizer"
        payload = {
            "model": self.settings.dashscope_tts_model,
            "input": {
                "text": text,
                "voice": selected_voice,
                "format": "mp3",
                "sample_rate": 24000,
                "language_hints": ["ja"],
            },
        }
        with httpx.Client(timeout=180.0, follow_redirects=True, trust_env=False) as client:
            response = client.post(
                endpoint,
                headers={"Authorization": f"Bearer {self.settings.dashscope_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            try:
                audio_url = body["output"]["audio"]["url"]
            except (KeyError, TypeError) as error:
                raise RuntimeError(f"DashScope TTS 未返回音频 URL: {body}") from error
            audio = client.get(audio_url)
            audio.raise_for_status()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(audio.content)
