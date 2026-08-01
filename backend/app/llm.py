from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def reply(self, messages: list[dict[str, str]]) -> str:
        providers = self._provider_order()
        errors: list[str] = []
        for index, provider in enumerate(providers):
            try:
                return self._reply_with(provider, messages)
            except (httpx.HTTPError, RuntimeError) as error:
                errors.append(f"{provider}: {error}")
                is_last = index == len(providers) - 1
                if is_last or not self.settings.llm_fallback_on_error:
                    raise RuntimeError("；".join(errors)) from error
        raise RuntimeError("没有可用的文本模型。")

    def _provider_order(self) -> list[str]:
        configured = self.settings.llm_provider.strip().lower()
        if configured not in {"auto", "dashscope", "deepseek"}:
            raise RuntimeError("LLM_PROVIDER 只接受 auto、dashscope 或 deepseek。")
        available = {
            "dashscope": bool(self.settings.dashscope_api_key),
            "deepseek": bool(self.settings.deepseek_api_key),
        }
        if configured != "auto":
            if not available[configured]:
                key = "DASHSCOPE_API_KEY" if configured == "dashscope" else "DEEPSEEK_API_KEY"
                raise RuntimeError(f"LLM_PROVIDER={configured}，但 {key} 尚未配置。")
            return [configured]
        order = [provider for provider in ("dashscope", "deepseek") if available[provider]]
        if not order:
            raise RuntimeError("DASHSCOPE_API_KEY 与 DEEPSEEK_API_KEY 均未配置。")
        return order

    def _reply_with(self, provider: str, messages: list[dict[str, str]]) -> str:
        if provider == "dashscope":
            base_url = self.settings.dashscope_chat_base_url
            api_key = self.settings.dashscope_api_key
            model = self.settings.dashscope_chat_model
        else:
            base_url = self.settings.deepseek_base_url
            api_key = self.settings.deepseek_api_key
            model = self.settings.deepseek_model
        assert api_key
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
            raise RuntimeError(f"{provider} 未返回可读取的回答。")
        return content.strip()
