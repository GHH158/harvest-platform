from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.learner_memory import (
    RECURRING_ERROR_MIN_EVENTS,
    RECURRING_ERROR_WINDOW_DAYS,
    build_memory_guidance,
    confidence_for,
    derive_recurring_error_memories,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def event(
    event_id: int,
    category: str,
    *,
    days_ago: int = 1,
    original: str = "原文",
    replacement: str = "修正",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "occurred_at": NOW - timedelta(days=days_ago),
        "payload": {
            "original": original,
            "replacement": replacement,
            "reason_zh": "理由",
            "category": category,
        },
    }


def test_a_category_below_the_threshold_is_not_a_memory() -> None:
    # Two corrections is a coincidence, not a pattern worth telling someone about.
    events = [event(index, "word_choice") for index in range(1, RECURRING_ERROR_MIN_EVENTS)]

    assert derive_recurring_error_memories(events, now=NOW) == []


def test_recurring_category_becomes_one_explainable_memory() -> None:
    events = [event(index, "word_choice") for index in range(1, 4)]
    events[-1] = event(3, "word_choice", days_ago=0, original="随时", replacement="いつでも")

    memories = derive_recurring_error_memories(events, now=NOW)

    assert len(memories) == 1
    memory = memories[0]
    assert memory.kind == "recurring_error_pattern"
    assert memory.subject_kind == "correction_category"
    assert memory.subject_key == "word_choice"
    assert memory.evidence_count == 3
    # Every supporting event is referenced, so the claim can be traced back.
    assert sorted(memory.evidence_refs) == [1, 2, 3]
    # The most recent correction is the example, and it is a real one.
    assert "「随时」→「いつでも」" in memory.content
    assert "词语选择" in memory.content
    assert memory.reason.startswith("近 90 天内有 3 条")
    assert memory.latest_evidence_at == NOW


def test_evidence_outside_the_window_stops_counting() -> None:
    """Without a window a memory only grows; a habit fixed long ago would stay
    attached to the learner forever."""
    stale = [
        event(index, "register", days_ago=RECURRING_ERROR_WINDOW_DAYS + 1) for index in range(1, 4)
    ]
    assert derive_recurring_error_memories(stale, now=NOW) == []

    mixed = [*stale, *(event(index, "register", days_ago=2) for index in range(10, 13))]
    memories = derive_recurring_error_memories(mixed, now=NOW)
    assert len(memories) == 1
    assert memories[0].evidence_count == 3
    assert sorted(memories[0].evidence_refs) == [10, 11, 12]


def test_confidence_is_an_ordinal_not_a_probability() -> None:
    # §5.11 refused to fabricate a 1.0 for uncalibrated model output; the same
    # judgement keeps this a support level rather than a fake percentage.
    assert confidence_for(3) == "weak"
    assert confidence_for(4) == "moderate"
    assert confidence_for(6) == "moderate"
    assert confidence_for(7) == "strong"
    assert confidence_for(70) == "strong"


def test_unknown_category_is_skipped_rather_than_guessed() -> None:
    events = [event(index, "invented_category") for index in range(1, 5)]

    assert derive_recurring_error_memories(events, now=NOW) == []


def test_memories_are_ordered_by_support_then_recency() -> None:
    events = [
        *(event(index, "grammar", days_ago=30) for index in range(1, 6)),
        *(event(index, "naturalness", days_ago=1) for index in range(10, 13)),
    ]

    memories = derive_recurring_error_memories(events, now=NOW)

    assert [memory.subject_key for memory in memories] == ["grammar", "naturalness"]
    assert memories[0].confidence == "moderate"
    assert memories[1].confidence == "weak"


def test_content_states_the_fact_without_evaluating_the_learner() -> None:
    # §1.4: no gamification, no encouragement, no scolding — the injected sentence
    # and the one shown in the app are the same sentence, so it has to stay neutral.
    events = [event(index, "grammar") for index in range(1, 4)]

    content = derive_recurring_error_memories(events, now=NOW)[0].content

    for forbidden in ("加油", "努力", "继续保持", "不够", "退步", "！"):
        assert forbidden not in content


def test_guidance_uses_the_memory_sentence_verbatim() -> None:
    memories = [{"content": "最近在语法上反复被纠正（近 90 天 4 次）"}]

    assert build_memory_guidance(memories) == "- 最近在语法上反复被纠正（近 90 天 4 次）"
