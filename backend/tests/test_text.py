import pytest
from app.text import canonical_source_key, estimated_segments, split_sentences


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


def test_youtube_share_parameter_does_not_create_a_new_identity() -> None:
    # The real duplicates: same video, a fresh `si` from each tap on 分享.
    first = canonical_source_key("https://youtu.be/AgWRJo8n8L8?si=1P4N7D15hXIfrGqF")
    second = canonical_source_key("https://youtu.be/AgWRJo8n8L8?si=zLpnn-jS4oaqLlee")
    assert first == second == "youtube:AgWRJo8n8L8"


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/AgWRJo8n8L8",
        "https://www.youtube.com/watch?v=AgWRJo8n8L8",
        "http://m.youtube.com/watch?v=AgWRJo8n8L8&feature=share",
        "https://www.youtube.com/shorts/AgWRJo8n8L8",
        "https://www.youtube.com/embed/AgWRJo8n8L8",
        "https://music.youtube.com/watch?v=AgWRJo8n8L8&list=RDAgWRJo8n8L8",
    ],
)
def test_every_youtube_form_collapses_to_the_video_id(url: str) -> None:
    assert canonical_source_key(url) == "youtube:AgWRJo8n8L8"


def test_different_youtube_videos_stay_distinct() -> None:
    assert canonical_source_key("https://youtu.be/AgWRJo8n8L8") != canonical_source_key(
        "https://youtu.be/J2tjySs8UbA"
    )


def test_generic_urls_ignore_scheme_www_trailing_slash_and_query_order() -> None:
    assert canonical_source_key("http://www.example.com/a/b/?y=2&x=1") == canonical_source_key(
        "https://example.com/a/b?x=1&y=2"
    )


def test_generic_urls_keep_meaningful_query_parameters() -> None:
    assert canonical_source_key("https://example.com/read?id=1") != canonical_source_key(
        "https://example.com/read?id=2"
    )


def test_non_http_input_cannot_be_compared() -> None:
    assert canonical_source_key("") == ""
    assert canonical_source_key("   ") == ""
    assert canonical_source_key("file:///tmp/a.mp4") == ""
