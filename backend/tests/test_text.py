import pytest
from app.text import estimated_segments, split_sentences


def test_splits_japanese_sentences_without_whitespace() -> None:
    assert split_sentences("雨です。次は晴れです！本当？") == ["雨です。", "次は晴れです！", "本当？"]


def test_estimates_all_sentences_inside_audio_duration() -> None:
    segments = estimated_segments("雨です。次は晴れです！", 4_000)
    assert [(segment["start_ms"], segment["end_ms"]) for segment in segments] == [
        (0, 1_455),
        (1_455, 4_000),
    ]


def test_empty_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="可朗读"):
        estimated_segments("\n  ", 1_000)
