import httpx
import pytest
from app.config import Settings
from app.llm import LLMService


def test_llm_requires_an_explicit_key() -> None:
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        LLMService(Settings(dashscope_api_key=None, deepseek_api_key=None)).reply([{"role": "user", "content": "こんにちは"}])


class Reply:
    def __init__(self, content: str) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self.content}}]}


def test_auto_provider_falls_back_to_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def post(url: str, **_: object) -> Reply:
        calls.append(url)
        if "dashscope" in url:
            raise httpx.ConnectError("Qwen quota unavailable")
        return Reply("DeepSeek 回答")

    monkeypatch.setattr("app.llm.httpx.post", post)
    settings = Settings(dashscope_api_key="qwen", deepseek_api_key="deepseek", llm_provider="auto")

    answer = LLMService(settings).reply([{"role": "user", "content": "こんにちは"}])

    assert answer == "DeepSeek 回答"
    assert len(calls) == 2


def test_explicit_deepseek_provider_does_not_call_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("app.llm.httpx.post", lambda url, **_: calls.append(url) or Reply("はい"))
    settings = Settings(
        dashscope_api_key="qwen",
        deepseek_api_key="deepseek",
        llm_provider="deepseek",
    )

    assert LLMService(settings).reply([{"role": "user", "content": "こんにちは"}]) == "はい"
    assert calls == ["https://api.deepseek.com/v1/chat/completions"]
