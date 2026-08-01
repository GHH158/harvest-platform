from pathlib import Path

import pytest
from app.config import Settings
from app.tts import TTSService
from app.voice import VoiceEnrollmentService, validate_voice_sample_duration


def test_voice_sample_must_be_between_three_and_thirty_seconds() -> None:
    validate_voice_sample_duration(3_000)
    validate_voice_sample_duration(30_000)
    with pytest.raises(RuntimeError, match="3–30 秒"):
        validate_voice_sample_duration(2_999)
    with pytest.raises(RuntimeError, match="3–30 秒"):
        validate_voice_sample_duration(30_001)


def test_tts_requires_a_japanese_capable_voice(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="支持日语"):
        TTSService(Settings(dashscope_api_key="configured", dashscope_tts_voice=None)).synthesize(
            text="雨です。", destination=tmp_path / "reading.mp3"
        )


def test_voice_enrollment_requires_key() -> None:
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        VoiceEnrollmentService(Settings(dashscope_api_key=None)).create_japanese_voice(
            audio_url="https://example.com/sample.m4a", prefix="mine"
        )


def test_voice_enrollment_sends_japanese_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"output": {"voice_id": "qwen-audio-3.0-tts-plus-mine-123"}}

    def post(url: str, **kwargs: object) -> Response:
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("app.voice.httpx.post", post)

    voice_id = VoiceEnrollmentService(Settings(dashscope_api_key="configured")).create_japanese_voice(
        audio_url="https://example.com/sample.m4a", prefix="mine"
    )

    assert voice_id.endswith("mine-123")
    assert captured["json"]["input"]["language_hints"] == ["ja"]
