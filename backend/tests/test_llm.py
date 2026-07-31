import pytest
from app.config import Settings
from app.llm import LLMService


def test_llm_requires_an_explicit_key() -> None:
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        LLMService(Settings(dashscope_api_key=None, deepseek_api_key=None)).reply([{"role": "user", "content": "こんにちは"}])
