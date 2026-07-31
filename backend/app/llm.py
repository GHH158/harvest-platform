from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def reply(self, messages: list[dict[str, str]]) -> str:
        if self.settings.dashscope_api_key:
            base_url = self.settings.dashscope_chat_base_url
            api_key = self.settings.dashscope_api_key
            model = self.settings.dashscope_chat_model
        elif self.settings.deepseek_api_key:
            base_url = self.settings.deepseek_base_url
            api_key = self.settings.deepseek_api_key
            model = self.settings.deepseek_model
        else:
            raise RuntimeError("DASHSCOPE_API_KEY 尚未配置；百炼免费额度用完后可改配 DEEPSEEK_API_KEY。")
        response = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "temperature": 0.4},
            timeout=90.0,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        content = payload.get("choices", [{}])[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("聊天模型未返回可读取的回答。")
        return content.strip()
