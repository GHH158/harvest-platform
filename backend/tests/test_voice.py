import math
import wave
from array import array
from pathlib import Path

import pytest
from app.config import Settings
from app.tts import TTSService
from app.voice import (
    ProbeRange,
    VideoVoiceExtractor,
    VoiceEnrollmentService,
    validate_video_voice_clip,
    validate_voice_sample_duration,
)


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


def test_video_voice_clip_accepts_auto_and_rejects_invalid_manual_range() -> None:
    validate_video_voice_clip(None, 20)
    validate_video_voice_clip(12.5, 3)
    with pytest.raises(RuntimeError, match="起点"):
        validate_video_voice_clip(-0.1, 20)
    with pytest.raises(RuntimeError, match="3–30 秒"):
        validate_video_voice_clip(None, 31)
    with pytest.raises(RuntimeError, match="有限数字"):
        validate_video_voice_clip(None, float("nan"))


def test_automatic_probes_cover_long_video_without_exceeding_eight() -> None:
    ranges = VideoVoiceExtractor._automatic_probe_ranges(600)

    assert len(ranges) == 8
    assert ranges[0] == (0.0, 30.0)
    assert ranges[-1] == (570.0, 30.0)


def test_quality_scoring_prefers_clearer_later_speech(tmp_path: Path) -> None:
    sample_rate = 8_000
    frame_samples = sample_rate // 10
    samples = array("h")
    for frame_index in range(200):
        in_clear_section = frame_index >= 100
        active = frame_index % 4 < 3
        amplitude = (9_000 if in_clear_section else 900) if active else 30
        for sample_index in range(frame_samples):
            value = round(amplitude * math.sin(2 * math.pi * 180 * sample_index / sample_rate))
            samples.append(value)
    source = tmp_path / "vocals.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(samples.tobytes())

    selected = VideoVoiceExtractor(tmp_path)._best_window(
        source,
        [ProbeRange(0, 0, 10), ProbeRange(50, 10, 10)],
        requested_duration=5,
    )

    assert selected.source_start_seconds >= 50
    assert selected.active_ratio >= 0.5
    assert selected.score > 0
