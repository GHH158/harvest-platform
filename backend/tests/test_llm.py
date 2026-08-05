import httpx
import pytest
from app.config import Settings
from app.llm import LLMService


def test_llm_requires_an_explicit_key() -> None:
    service = LLMService(Settings(dashscope_api_key=None, deepseek_api_key=None))
    try:
        with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
            service.reply([{"role": "user", "content": "こんにちは"}])
    finally:
        service.close()


def test_default_text_model_is_qwen37_max() -> None:
    assert Settings(_env_file=None).dashscope_chat_model == "qwen3.7-max"


class Reply:
    def __init__(self, content: str) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self.content}}]}


def test_auto_provider_falls_back_to_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    models: list[str] = []

    def post(_: httpx.Client, url: str, **values: object) -> Reply:
        calls.append(url)
        payload = values["json"]
        assert isinstance(payload, dict)
        models.append(str(payload["model"]))
        if "dashscope" in url:
            raise httpx.ConnectError("Qwen quota unavailable")
        return Reply("DeepSeek 回答")

    monkeypatch.setattr(httpx.Client, "post", post)
    settings = Settings(dashscope_api_key="qwen", deepseek_api_key="deepseek", llm_provider="auto")
    service = LLMService(settings)

    try:
        answer = service.reply([{"role": "user", "content": "こんにちは"}])
    finally:
        service.close()

    assert answer == "DeepSeek 回答"
    assert len(calls) == 2
    assert models == ["qwen3.7-max", "deepseek-v4-flash"]


def test_explicit_deepseek_provider_does_not_call_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(httpx.Client, "post", lambda _, url, **__: calls.append(url) or Reply("はい"))
    settings = Settings(
        dashscope_api_key="qwen",
        deepseek_api_key="deepseek",
        llm_provider="deepseek",
    )

    service = LLMService(settings)
    try:
        assert service.reply([{"role": "user", "content": "こんにちは"}]) == "はい"
    finally:
        service.close()
    assert calls == ["https://api.deepseek.com/v1/chat/completions"]


def test_dashscope_learning_request_disables_thinking_and_uses_json_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads: list[dict] = []

    def post(_: httpx.Client, url: str, **values: object) -> Reply:
        assert url == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        payload = values["json"]
        assert isinstance(payload, dict)
        payloads.append(payload)
        return Reply('{"reply":"はい"}')

    monkeypatch.setattr(httpx.Client, "post", post)
    service = LLMService(Settings(dashscope_api_key="qwen", deepseek_api_key=None))
    try:
        service.reply(
            [{"role": "user", "content": "こんにちは"}],
            enable_thinking=False,
            json_mode=True,
            max_tokens=1_200,
        )
    finally:
        service.close()

    assert payloads == [
        {
            "model": "qwen3.7-max",
            "messages": [{"role": "user", "content": "こんにちは"}],
            "temperature": 0.4,
            "enable_thinking": False,
            "response_format": {"type": "json_object"},
            "max_tokens": 1_200,
        }
    ]
