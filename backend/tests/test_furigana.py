from __future__ import annotations

import pytest
from app import main
from app.furigana import furigana_available, ruby_segments

pytestmark = pytest.mark.skipif(not furigana_available(), reason="requires the furigana extra (janome)")


def test_ruby_segments_marks_kanji_with_hiragana_reading() -> None:
    segments = ruby_segments("昨日、映画を見ました。")
    readings = {s["surface"]: s["reading"] for s in segments if s["reading"]}

    assert readings["昨日"] == "きのう"
    assert readings["映画"] == "えいが"
    assert readings["見"] == "み"
    # Punctuation and kana particles carry no reading.
    assert next(s for s in segments if s["surface"] == "、")["reading"] is None
    assert next(s for s in segments if s["surface"] == "を")["reading"] is None


def test_furigana_returns_plain_text_when_no_kanji() -> None:
    segments = ruby_segments("こんにちは。")
    assert segments and all(s["reading"] is None for s in segments)


def test_furigana_endpoint_returns_segments() -> None:
    result = main.furigana(main.FuriganaRequest(text="日本語を勉強しています。"))

    assert result["segments"]
    assert any(s["surface"] == "日本語" and s["reading"] == "にほんご" for s in result["segments"])
