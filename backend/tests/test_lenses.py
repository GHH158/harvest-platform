from __future__ import annotations

import pytest
from app.companion import build_companion_messages
from app.lenses import (
    LENS_PROMPT_VERSION,
    QUESTION_LENSES,
    lens_by_id,
    public_lenses,
    render_lens_question,
)


def test_every_lens_renders_a_human_readable_question_never_an_id() -> None:
    """§5.15: history is read by a person, so `lens=structure` must never be stored."""

    for lens in QUESTION_LENSES:
        plain = render_lens_question(lens, None)
        focused = render_lens_question(lens, "近所")

        assert lens.id not in plain and lens.id not in focused
        assert plain.endswith("？")
        assert "近所" in focused
        assert "{focus}" not in focused


def test_blank_focus_falls_back_to_the_sentence_level_question() -> None:
    lens = lens_by_id("meaning")
    assert lens is not None

    assert render_lens_question(lens, "   ") == lens.question_zh
    assert render_lens_question(lens, None) == lens.question_zh


def test_unknown_lens_is_not_silently_resolved() -> None:
    assert lens_by_id("grammar") is None
    assert lens_by_id("") is None
    assert lens_by_id("STRUCTURE") is not None  # case-insensitive, but must exist


def test_lens_ids_and_order_are_stable() -> None:
    """The three non-meaning angles came from the blind-tested perspectives (see
    docs/reviews/M2-role-blind-evaluation.md). The roles themselves were removed; the
    ids stay fixed because they are recorded in companion_message.lens."""

    assert [lens.id for lens in QUESTION_LENSES] == [
        "meaning", "naturalness", "structure", "chinese",
    ]


def test_lens_focus_reaches_the_model_without_replacing_the_question() -> None:
    lens = lens_by_id("structure")
    assert lens is not None
    question = render_lens_question(lens, None)

    messages = build_companion_messages(
        context=[{"idx": 0, "text_ja": "近所にコンビニがある。"}],
        history=[],
        question=question,
        lens_focus=lens.focus_zh,
    )

    user_content = messages[-1]["content"]
    assert question in user_content
    assert "只回答这个角度" in user_content
    assert lens.focus_zh in user_content


def test_no_lens_leaves_the_turn_exactly_as_before() -> None:
    with_lens = build_companion_messages(
        context=[], history=[], question="这句怎么理解？", lens_focus=None
    )
    assert "只回答这个角度" not in with_lens[-1]["content"]


def test_public_lenses_expose_only_id_and_label() -> None:
    """The client must not receive the prompt text — it sends an id and nothing else."""

    rows = public_lenses()

    assert [row["id"] for row in rows] == ["meaning", "naturalness", "structure", "chinese"]
    for row in rows:
        assert set(row) == {"id", "label_zh"}
        assert row["label_zh"]


def test_lens_prompt_version_is_set() -> None:
    assert LENS_PROMPT_VERSION.startswith("companion-lens-")


@pytest.mark.parametrize("lens_id", [lens.id for lens in QUESTION_LENSES])
def test_each_lens_states_what_not_to_answer(lens_id: str) -> None:
    """An angle that only says what to cover still drifts into a full answer — the
    same failure the first version of these prompts had."""

    lens = lens_by_id(lens_id)
    assert lens is not None
    assert any(marker in lens.focus_zh for marker in ("不要", "不需要", "分开", "只"))


def test_labels_stay_short_enough_to_read_at_a_glance() -> None:
    """§11.9 twice decided this wording (§5.15).

    The first reworded set did not fit one row on a 402pt screen and the horizontal scroll
    clipped 「跟中文差在哪」 to 「跟中文差在」 — a label you cannot read is a label you will
    not use, and you go back to always tapping the first one. The budget below is what fits
    at the default text size; blow it and the clipping returns.
    """

    labels = [lens.label_zh for lens in QUESTION_LENSES]
    assert labels == ["啥意思？", "怪不怪", "拆开看看", "跟中文比"]
    assert sum(len(label) for label in labels) <= 15
    assert all(len(label) <= 4 for label in labels)


def test_rewording_the_labels_did_not_touch_what_the_model_sees() -> None:
    """Only `label_zh` changed on 2026-08-10, which is why LENS_PROMPT_VERSION stands: the
    stored question and the prompt focus are unchanged, so a later trace diff still means
    what it used to mean."""

    assert LENS_PROMPT_VERSION == "companion-lens-v1"
    by_id = {lens.id: lens for lens in QUESTION_LENSES}
    assert by_id["meaning"].question_zh == "这句话是什么意思？"
    assert by_id["naturalness"].question_zh == "这句话听起来自然吗？语体合适吗？"
    assert by_id["structure"].question_zh == "这句话的语法结构是怎样的？"
    assert by_id["chinese"].question_zh == "这句话和中文的说法有什么不同？"
    # None of the colloquial labels leaked into the prompt.
    for lens in QUESTION_LENSES:
        assert lens.label_zh not in lens.focus_zh
