from __future__ import annotations

import importlib.util

_TOKENIZER = None


def furigana_available() -> bool:
    return importlib.util.find_spec("janome") is not None


def _get_tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        from janome.tokenizer import Tokenizer

        _TOKENIZER = Tokenizer()
    return _TOKENIZER


def _to_hiragana(text: str) -> str:
    # Katakana block U+30A1..U+30F6 is exactly 0x60 above hiragana.
    return "".join(
        chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text
    )


def _contains_kanji(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def ruby_segments(text: str) -> list[dict[str, str | None]]:
    """Tokenize Japanese and mark kanji tokens with their reading (hiragana).

    Returns a list of ``{"surface": ..., "reading": ... | None}`` segments.
    Non-kanji tokens carry ``reading: None`` so the client only renders ruby
    where a reading exists.
    """
    if not furigana_available():
        raise RuntimeError("尚未安装假名标注组件；请运行 ./.venv/bin/pip install -e '.[furigana]' 后重启服务。")
    segments: list[dict[str, str | None]] = []
    for token in _get_tokenizer().tokenize(text.strip()):
        surface = token.surface
        if _contains_kanji(surface):
            segments.append({"surface": surface, "reading": _to_hiragana(token.reading)})
        else:
            segments.append({"surface": surface, "reading": None})
    return segments
