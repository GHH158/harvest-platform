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
from app.roles import ROLES_BY_ID


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


def test_non_meaning_lenses_mirror_the_verified_role_perspectives() -> None:
    """The angles are deliberately the three M2 lenses so M3 can promote them
    without renaming anything the learner has already learned to recognise."""

    mapped = {lens.id: lens.role_id for lens in QUESTION_LENSES}

    assert mapped == {
        "meaning": None,
        "naturalness": "aoi",
        "structure": "kei",
        "chinese": "lin",
    }
    for role_id in ("aoi", "kei", "lin"):
        assert role_id in ROLES_BY_ID


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
    same failure role-perspective-v1 had (§5.14)."""

    lens = lens_by_id(lens_id)
    assert lens is not None
    assert any(marker in lens.focus_zh for marker in ("不要", "不需要", "分开", "只"))
