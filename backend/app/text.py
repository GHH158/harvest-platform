from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse

_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?])")

# Share/analytics parameters that change per copy without changing the resource.
# YouTube's `si` is the reason the same video got imported three times.
_TRACKING_PARAMS = {
    "si", "feature", "app", "spm", "share_source", "share_medium",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "igshid",
}

_YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}
_YOUTUBE_PATH_PREFIXES = ("/shorts/", "/embed/", "/v/", "/live/")


def _youtube_video_id(host: str, path: str, query: list[tuple[str, str]]) -> str | None:
    if host == "youtu.be":
        candidate = path.strip("/").split("/")[0]
        return candidate or None
    if host not in _YOUTUBE_HOSTS:
        return None
    if path == "/watch":
        for key, value in query:
            if key == "v" and value:
                return value
        return None
    for prefix in _YOUTUBE_PATH_PREFIXES:
        if path.startswith(prefix):
            candidate = path[len(prefix):].split("/")[0]
            return candidate or None
    return None


def canonical_source_key(url: str) -> str:
    """Stable identity for an imported link, so the same source is recognised again.

    Normalises the differences that do not change what gets downloaded: scheme,
    `www.`, trailing slash, query order, and per-share tracking parameters. Every
    YouTube share form collapses to the bare video id. Returns "" for input that
    is not a usable http(s) URL, which callers treat as "cannot compare".
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""

    host = (parsed.hostname or "").lower()
    host = host.removeprefix("www.")
    path = parsed.path or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key.lower() not in _TRACKING_PARAMS
    ]

    video_id = _youtube_video_id(host, path, query)
    if video_id:
        return f"youtube:{video_id}"

    normalized_path = path.rstrip("/") or "/"
    query.sort()
    suffix = f"?{urlencode(query)}" if query else ""
    return f"{host}{normalized_path}{suffix}"


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
        result.append({"idx": idx, "text_ja": sentence, "start_ms": cursor, "end_ms": max(cursor + 1, end_ms)})
        cursor = end_ms
    return result
