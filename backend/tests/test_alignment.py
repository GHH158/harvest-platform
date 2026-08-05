from app.alignment import align_words_to_source
from app.asr import RecognizedWord, parse_words


def test_alignment_keeps_original_text_and_donates_matching_times() -> None:
    result = align_words_to_source(
        "雨です。晴れです。",
        [RecognizedWord(text="雨です", start_ms=0, end_ms=600), RecognizedWord(text="晴れです", start_ms=700, end_ms=1_400)],
    )

    assert result.coverage == 1.0
    assert "".join(token.surface for token in result.tokens) == "雨です晴れです"
    assert result.tokens[0].start_ms == 0
    assert result.tokens[-1].end_ms == 1_400


def test_alignment_emits_japanese_words_with_hiragana_readings() -> None:
    result = align_words_to_source(
        "今日は少し風が強いです。",
        [RecognizedWord(text="今日は少し風が強いです", start_ms=0, end_ms=1_400)],
    )

    assert [token.surface for token in result.tokens] == ["今日", "は", "少し", "風", "が", "強い", "です"]
    assert result.tokens[0].reading == "きょう"
    assert result.tokens[5].reading == "つよい"
    assert result.tokens[0].start_ms == 0
    assert result.tokens[-1].end_ms == 1_400


def test_alignment_keeps_inflected_verbs_as_comprehensible_units() -> None:
    text = "本を買って読みたいと思います。"
    result = align_words_to_source(text, [RecognizedWord(text=text, start_ms=0, end_ms=1_500)])

    assert [token.surface for token in result.tokens] == ["本", "を", "買って", "読みたい", "と", "思います"]
    assert [token.reading for token in result.tokens] == ["ほん", "を", "かって", "よみたい", "と", "おもいます"]


def test_alignment_reports_partial_coverage_without_rewriting_source() -> None:
    result = align_words_to_source("雨です。晴れです。", [RecognizedWord(text="雨です", start_ms=0, end_ms=600)])

    assert 0 < result.coverage < 1
    assert "".join(token.surface for token in result.tokens) == "雨です"


def test_parse_words_reads_documented_fun_asr_shape() -> None:
    payload = {
        "transcripts": [
            {"sentences": [{"words": [{"text": "雨", "begin_time": 10, "end_time": 120}]}]}
        ]
    }

    assert parse_words(payload) == [RecognizedWord(text="雨", start_ms=10, end_ms=120)]
