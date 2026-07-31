from __future__ import annotations

from difflib import SequenceMatcher


def score_transcript(expected: str, actual: str) -> tuple[float, list[dict[str, object]]]:
    """Return an explainable character-unit fallback for Japanese shadowing."""
    expected_units = [item for item in expected if not item.isspace()]
    actual_units = [item for item in actual if not item.isspace()]
    matcher = SequenceMatcher(a="".join(expected_units), b="".join(actual_units), autojunk=False)
    matched: set[int] = set()
    for tag, start, end, _, _ in matcher.get_opcodes():
        if tag == "equal":
            matched.update(range(start, end))
    units = [{"surface": value, "recognized": index in matched} for index, value in enumerate(expected_units)]
    score = len(matched) / len(expected_units) if expected_units else 0.0
    return score, units
