from app.shadowing import score_transcript


def test_shadowing_score_marks_missing_characters() -> None:
    score, diff = score_transcript("雨です。", "雨です")
    assert score > 0.7
    assert any(not item["recognized"] for item in diff)
