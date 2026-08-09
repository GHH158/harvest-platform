"""Learner memory derivation rules (§5.12).

A memory is a claim about the *person* that spans many objects — "recently keeps
being corrected on particles" — as opposed to LearnerState, which is per-object
(`grammar_encounter` already answers "how is this one grammar point doing").
The test is simple: if it hangs off a single subject_key and should vanish when
that object is deleted, it is state; if it only holds once several objects'
evidence is added up, it is memory.

Everything here is a pure function over already-fetched events so the rule can be
tested without a database, and so a rebuild is deterministic: the same events and
the same rule version always produce the same memories.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

LEARNER_MEMORY_SCHEMA_VERSION = "learner-memory-v1"

# Bumping this marks every existing memory as produced by an older rule, so a
# rebuild can be told apart from "the evidence changed".
RECURRING_ERROR_RULE_VERSION = "recurring-error-pattern-v1"

RECURRING_ERROR_MIN_EVENTS = 3
# Without a window a memory only ever grows. A habit fixed six months ago should
# not stay attached to the learner: once no fresh evidence lands inside the
# window, the next rebuild drops the memory on its own.
RECURRING_ERROR_WINDOW_DAYS = 90

# Matches the §4.3 injection contract: at most three categories, 600 characters.
MAX_INJECTED_MEMORIES = 3
MAX_GUIDANCE_CHARACTERS = 600

CORRECTION_CATEGORY_LABELS_ZH = {
    "grammar": "语法",
    "word_choice": "词语选择",
    "naturalness": "自然度",
    "register": "语体",
    "orthography": "书写",
}


@dataclass(frozen=True)
class MemoryDraft:
    """One derived memory, before it is written to `learner_memory`.

    Deliberately carries no `dismissed_at`: that field is the learner's explicit
    rejection, a new fact rather than something a rule can derive, so a rebuild
    must never be in a position to overwrite it.
    """

    kind: str
    subject_kind: str
    subject_key: str
    content: str
    reason: str
    confidence: str
    evidence_count: int
    evidence_refs: list[int]
    latest_evidence_at: datetime
    rule_version: str


def confidence_for(evidence_count: int) -> str:
    """An ordinal support level, not a probability.

    §5.11 already refused to store a fabricated `1.0` for the model's grammar
    classification; the same judgement applies here. Three corrections support a
    claim, but nothing calibrates them into "50% likely to be true", so this stays
    weak/moderate/strong next to the raw `evidence_count` and is never rendered as
    a percentage or a progress bar.
    """
    if evidence_count >= 7:
        return "strong"
    if evidence_count >= 4:
        return "moderate"
    return "weak"


def derive_recurring_error_memories(
    events: list[Mapping[str, Any]],
    *,
    now: datetime,
    min_events: int = RECURRING_ERROR_MIN_EVENTS,
    window_days: int = RECURRING_ERROR_WINDOW_DAYS,
) -> list[MemoryDraft]:
    """Group real corrections by category and keep the ones that recur.

    `events` are `correction_item` learning events (already filtered to exclude
    rejected ones by the caller), each with `id`, `occurred_at` and a `payload`
    holding `category` / `original` / `replacement`. Only genuine corrections
    count: §13.2 forbids feeding the model's own output back in as the learner's
    memory, so nothing derived from an assistant turn belongs here.
    """
    cutoff = now - timedelta(days=window_days)
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        occurred_at = event["occurred_at"]
        if occurred_at < cutoff:
            continue
        payload = event.get("payload") or {}
        category = str(payload.get("category") or "").strip()
        if category not in CORRECTION_CATEGORY_LABELS_ZH:
            # An unknown category cannot be described honestly in Chinese, and
            # guessing a label would put words in the learner's mouth.
            continue
        grouped.setdefault(category, []).append(event)

    drafts: list[MemoryDraft] = []
    for category, category_events in grouped.items():
        if len(category_events) < min_events:
            continue
        ordered = sorted(
            category_events,
            key=lambda item: (item["occurred_at"], int(item["id"])),
            reverse=True,
        )
        latest_payload = ordered[0].get("payload") or {}
        label = CORRECTION_CATEGORY_LABELS_ZH[category]
        count = len(ordered)
        content = (
            f"最近在{label}上反复被纠正（近 {window_days} 天 {count} 次），"
            f"例如「{latest_payload.get('original', '')}」→「{latest_payload.get('replacement', '')}」"
        )
        drafts.append(
            MemoryDraft(
                kind="recurring_error_pattern",
                subject_kind="correction_category",
                subject_key=category,
                content=content,
                reason=f"近 {window_days} 天内有 {count} 条该类别的真实纠错，达到 {min_events} 条阈值",
                confidence=confidence_for(count),
                evidence_count=count,
                evidence_refs=[int(event["id"]) for event in ordered],
                latest_evidence_at=ordered[0]["occurred_at"],
                rule_version=RECURRING_ERROR_RULE_VERSION,
            )
        )
    # Strongest first, then most recent: the injection budget below keeps only a
    # few, and the best-supported observation is the one worth spending it on.
    drafts.sort(key=lambda draft: (-draft.evidence_count, -draft.latest_evidence_at.timestamp()))
    return drafts


def build_memory_guidance(
    memories: list[Mapping[str, Any]],
    *,
    max_characters: int = MAX_GUIDANCE_CHARACTERS,
    max_memories: int = MAX_INJECTED_MEMORIES,
) -> str:
    """Render active memories into the light personalisation block for the prompt.

    The injected line is the memory's own `content`, verbatim — the same sentence
    the learner can read back through `GET /learner/memories`. Keeping one wording
    for both prevents the interface from sounding gentle while the prompt sounds
    severe. Callers pass only non-dismissed memories, so a dismissal takes effect
    on the very next turn instead of merely hiding a row in some list.
    """
    selected = list(memories)[:max_memories]
    if not selected:
        return ""
    line_budget = max(1, (max_characters - max(0, len(selected) - 1)) // len(selected))
    lines = [f"- {str(memory['content'])}"[:line_budget] for memory in selected]
    return "\n".join(lines)
