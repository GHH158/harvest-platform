from __future__ import annotations

import base64
from pathlib import Path

import httpx

from .config import Settings


class VisionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract_japanese(self, image_path: Path) -> str:
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY 尚未配置；配置后才能识别照片中的日语。")
        mime = "image/jpeg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode()
        payload = {"model": self.settings.dashscope_vl_model, "messages": [{"role": "user", "content": [
            {"type": "text", "text": "提取图片中的日语正文。只返回正文，不要翻译、说明或 Markdown。"},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]}]}
        response = httpx.post(
            f"{self.settings.dashscope_chat_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.dashscope_api_key}"}, json=payload, timeout=90.0,
        )
        response.raise_for_status()
        text = response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not text:
            raise RuntimeError("百炼视觉模型未返回可朗读的日语正文。")
        return text
