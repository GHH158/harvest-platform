from __future__ import annotations

import re

_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?])")


def split_sentences(text: str) -> list[str]:
    """P1's intentionally simple Japanese sentence splitter."""
    normalized = re.sub(r"[\r\n]+", " ", text).strip()
    candidates = _SENTENCE_BOUNDARY.split(normalized)
    return [candidate.strip() for candidate in candidates if candidate.strip()]


def estimated_segments(text: str, duration_ms: int) -> list[dict[str, int | str]]:
    sentences = split_sentences(text)
    if not sentences:
        raise ValueError("没有可朗读的文本。")

    weights = [max(1, len(re.sub(r"\s", "", sentence))) for sentence in sentences]
    total_weight = sum(weights)
    cursor = 0
    result: list[dict[str, int | str]] = []
    for idx, (sentence, weight) in enumerate(zip(sentences, weights, strict=True)):
        if idx == len(sentences) - 1:
            end_ms = duration_ms
        else:
            end_ms = round(duration_ms * (sum(weights[: idx + 1]) / total_weight))
        result.append(
            {"idx": idx, "text_ja": sentence, "start_ms": cursor, "end_ms": max(cursor + 1, end_ms)}
        )
        cursor = end_ms
    return result
