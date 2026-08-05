from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from janome.tokenizer import Tokenizer

from .asr import RecognizedWord
from .text import split_sentences

_IGNORABLE = re.compile(r"[\s、。！？!?，,.…ー・『』「」（）()\[\]{}]+")
_TOKENIZER = Tokenizer()


@dataclass(frozen=True)
class AlignedToken:
    segment_idx: int
    idx: int
    surface: str
    reading: str | None
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


@dataclass
class _MorphologicalWord:
    surface: str
    reading: str | None
    normalized_surface: str
    head_part_of_speech: str


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


def _hiragana_reading(value: str) -> str | None:
    if not value or value == "*":
        return None
    converted: list[str] = []
    for character in value:
        codepoint = ord(character)
        if 0x30A1 <= codepoint <= 0x30F6 or 0x30FD <= codepoint <= 0x30FF:
            converted.append(chr(codepoint - 0x60))
        else:
            converted.append(character)
    return "".join(converted)


def _morphological_words(sentence: str) -> list[_MorphologicalWord]:
    words: list[_MorphologicalWord] = []
    for token in _TOKENIZER.tokenize(sentence):
        normalized_surface = _normalise(token.surface)
        if not normalized_surface:
            continue
        part_of_speech = token.part_of_speech.split(",")
        major = part_of_speech[0]
        detail = part_of_speech[1] if len(part_of_speech) > 1 else ""
        reading = _hiragana_reading(token.reading)
        merges_with_verb = bool(words) and words[-1].head_part_of_speech == "動詞" and (
            major == "助動詞" or (major == "助詞" and detail == "接続助詞" and token.surface in {"て", "で"})
        )
        if merges_with_verb:
            previous = words[-1]
            previous.surface += token.surface
            previous.normalized_surface += normalized_surface
            if previous.reading is not None and reading is not None:
                previous.reading += reading
            else:
                previous.reading = previous.reading or reading
            continue
        words.append(
            _MorphologicalWord(
                surface=token.surface,
                reading=reading,
                normalized_surface=normalized_surface,
                head_part_of_speech=major,
            )
        )
    return words


def align_words_to_source(source_text: str, words: list[RecognizedWord]) -> AlignmentResult:
    """Map ASR timestamps onto morphological words from the original Japanese.

    ASR text is not trusted as content: only matching spans donate time. A
    mismatch simply lowers coverage so callers can retain P1 sentence timing.
    """
    source_sentences = split_sentences(source_text)
    source_chars: list[tuple[int, str]] = []
    segment_offsets: list[int] = []
    for sentence_idx, sentence in enumerate(source_sentences):
        segment_offsets.append(len(source_chars))
        source_chars.extend((sentence_idx, character) for character in _normalise(sentence))
    asr_text, asr_timing = _character_timing(words)
    source_text_normalized = "".join(character for _, character in source_chars)
    matcher = SequenceMatcher(a=source_text_normalized, b=asr_text, autojunk=False)

    source_timing: list[tuple[int, int] | None] = [None] * len(source_chars)
    covered = 0
    for tag, source_start, source_end, asr_start, asr_end in matcher.get_opcodes():
        if tag != "equal":
            continue
        covered += source_end - source_start
        for offset in range(source_end - source_start):
            source_timing[source_start + offset] = asr_timing[asr_start + offset]

    tokens: list[AlignedToken] = []
    for segment_idx, sentence in enumerate(source_sentences):
        normalized_cursor = 0
        token_idx = 0
        for word in _morphological_words(sentence):
            normalized_surface = word.normalized_surface
            start = segment_offsets[segment_idx] + normalized_cursor
            end = start + len(normalized_surface)
            normalized_cursor += len(normalized_surface)
            matched_times = [timing for timing in source_timing[start:end] if timing is not None]
            if not matched_times:
                continue
            tokens.append(
                AlignedToken(
                    segment_idx=segment_idx,
                    idx=token_idx,
                    surface=word.surface,
                    reading=word.reading,
                    start_ms=matched_times[0][0],
                    end_ms=matched_times[-1][1],
                )
            )
            token_idx += 1
    return AlignmentResult(tokens=tokens, covered_characters=covered, total_characters=len(source_chars))
