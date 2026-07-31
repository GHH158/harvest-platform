from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .asr import RecognizedWord
from .text import split_sentences

_IGNORABLE = re.compile(r"[\s、。！？!?，,.…ー・『』「」（）()\[\]{}]+")


@dataclass(frozen=True)
class AlignedToken:
    segment_idx: int
    idx: int
    surface: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class AlignmentResult:
    tokens: list[AlignedToken]
    covered_characters: int
    total_characters: int

    @property
    def coverage(self) -> float:
        return self.covered_characters / self.total_characters if self.total_characters else 0.0


def _normalise(value: str) -> str:
    return _IGNORABLE.sub("", value)


def _character_timing(words: list[RecognizedWord]) -> tuple[str, list[tuple[int, int]]]:
    characters: list[str] = []
    timings: list[tuple[int, int]] = []
    for word in words:
        normalized = _normalise(word.text)
        if not normalized:
            continue
        width = len(normalized)
        duration = max(width, word.end_ms - word.start_ms)
        for index, character in enumerate(normalized):
            start_ms = word.start_ms + round(duration * index / width)
            end_ms = word.start_ms + round(duration * (index + 1) / width)
            characters.append(character)
            timings.append((start_ms, max(start_ms + 1, end_ms)))
    return "".join(characters), timings


def align_words_to_source(source_text: str, words: list[RecognizedWord]) -> AlignmentResult:
    """Map ASR timestamps back onto original Japanese characters.

    ASR text is not trusted as content: only matching spans donate time. A
    mismatch simply lowers coverage so callers can retain P1 sentence timing.
    """
    source_sentences = split_sentences(source_text)
    source_chars: list[tuple[int, str]] = []
    for sentence_idx, sentence in enumerate(source_sentences):
        source_chars.extend((sentence_idx, character) for character in _normalise(sentence))
    asr_text, asr_timing = _character_timing(words)
    source_text_normalized = "".join(character for _, character in source_chars)
    matcher = SequenceMatcher(a=source_text_normalized, b=asr_text, autojunk=False)

    raw_tokens: dict[int, list[tuple[str, int, int]]] = {}
    covered = 0
    for tag, source_start, source_end, asr_start, asr_end in matcher.get_opcodes():
        if tag != "equal":
            continue
        covered += source_end - source_start
        for offset in range(source_end - source_start):
            segment_idx, surface = source_chars[source_start + offset]
            start_ms, end_ms = asr_timing[asr_start + offset]
            raw_tokens.setdefault(segment_idx, []).append((surface, start_ms, end_ms))

    tokens: list[AlignedToken] = []
    for segment_idx, parts in raw_tokens.items():
        # Consecutive Japanese characters are rendered as individual timing
        # units. This remains robust when ASR tokenisation differs from the
        # original text and still supports word-like highlight animation.
        for token_idx, (surface, start_ms, end_ms) in enumerate(parts):
            tokens.append(AlignedToken(segment_idx, token_idx, surface, start_ms, end_ms))
    return AlignmentResult(tokens=tokens, covered_characters=covered, total_characters=len(source_chars))
