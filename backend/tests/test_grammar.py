from __future__ import annotations

from app.grammar_catalogue import GRAMMAR_CATALOGUE, catalogue_rows


def test_catalogue_keys_are_unique_and_stable() -> None:
    keys = [row[0] for row in GRAMMAR_CATALOGUE]
    assert len(keys) == len(set(keys))
    # Keys are the join target for corrections, so they must not carry spacing or case.
    assert all(key == key.strip().lower() for key in keys)
    assert all(" " not in key for key in keys)


def test_catalogue_covers_the_points_the_learner_actually_tripped_on() -> None:
    keys = {row[0] for row in GRAMMAR_CATALOGUE}
    for key in ("i-adj-past", "verb-potential", "verb-te-iru", "verb-te-aru", "particle-wa", "particle-ga"):
        assert key in keys


def test_catalogue_is_an_index_not_content() -> None:
    # §1.4 still forbids transcribing textbook material: the catalogue carries a
    # short label only, never an explanation or an example sentence.
    for _, title_ja, title_zh, _, _ in GRAMMAR_CATALOGUE:
        assert len(title_ja) <= 24
        assert len(title_zh) <= 16
        assert "。" not in title_zh and "。" not in title_ja


def test_catalogue_rows_are_ordered_and_complete() -> None:
    rows = catalogue_rows()
    assert len(rows) == len(GRAMMAR_CATALOGUE)
    assert [row["sort_order"] for row in rows] == list(range(len(rows)))
    assert {row["level"] for row in rows} <= {"N5", "N4", "N3"}
    assert all(row["category"] for row in rows)


def test_correction_items_only_accept_real_catalogue_keys() -> None:
    from app.chat import CorrectionItemOutput

    base = {"original": "読むています", "replacement": "読んでいます", "reason_zh": "て形", "category": "grammar"}
    assert CorrectionItemOutput(**base, grammar_key="verb-te").grammar_key == "verb-te"
    # A key the model invented is dropped rather than failing the whole turn: a bad
    # tag should cost the tag, not the correction.
    assert CorrectionItemOutput(**base, grammar_key="totally-made-up").grammar_key is None
    assert CorrectionItemOutput(**base, grammar_key="  ").grammar_key is None
    assert CorrectionItemOutput(**base).grammar_key is None


def test_chat_prompt_carries_the_catalogue_so_the_model_can_tag() -> None:
    from app.chat import CHAT_SYSTEM_PROMPT

    assert "i-adj-past = ～かった" in CHAT_SYSTEM_PROMPT
    assert "verb-te-iru = ～ている" in CHAT_SYSTEM_PROMPT
    # And the instruction that a wrong tag is worse than none.
    assert "worse than leaving it empty" in CHAT_SYSTEM_PROMPT
