from __future__ import annotations

from typing import Any

import pytest
from app import main
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


def test_grammar_evidence_fingerprint_is_deterministic_and_changes_with_evidence() -> None:
    evidence = [
        {"kind": "correction", "id": 17, "created_at": "ignored", "reason_zh": "ignored"},
        {"kind": "companion_question", "id": 23, "created_at": "ignored", "question": "ignored"},
    ]

    first_fingerprint, first_refs = main._grammar_evidence_fingerprint(evidence)
    second_fingerprint, second_refs = main._grammar_evidence_fingerprint([dict(item) for item in evidence])
    changed_fingerprint, changed_refs = main._grammar_evidence_fingerprint(
        [*evidence, {"kind": "correction", "id": 31}]
    )

    assert first_fingerprint == second_fingerprint
    assert first_refs == second_refs == [
        {"kind": "correction", "id": 17},
        {"kind": "companion_question", "id": 23},
    ]
    assert changed_fingerprint != first_fingerprint
    assert changed_refs[-1] == {"kind": "correction", "id": 31}


class GrammarExplanationRepository:
    def __init__(
        self,
        *,
        prompt_version: str,
        evidence_fingerprint: str,
        evidence: list[dict[str, Any]],
    ) -> None:
        self.evidence = evidence
        self.point = {
            "id": 1,
            "key": "verb-te-oku",
            "title_ja": "～ておく",
            "title_zh": "预先做好",
            "level": "N4",
            "status": "encountered",
            "explanation": "已有讲解",
            "explanation_prompt_version": prompt_version,
            "explanation_evidence_fingerprint": evidence_fingerprint,
        }
        self.saved: dict[str, Any] | None = None
        self.marked: list[dict[str, Any]] = []

    def get_grammar_point(self, key: str) -> dict[str, Any] | None:
        return dict(self.point) if key == self.point["key"] else None

    def grammar_evidence(self, key: str) -> list[dict[str, Any]]:
        return self.evidence

    def save_grammar_explanation(self, key: str, content: str, **metadata: Any) -> None:
        self.saved = {"key": key, "content": content, **metadata}
        self.point["explanation"] = content
        self.point["explanation_prompt_version"] = metadata["prompt_version"]
        self.point["explanation_evidence_fingerprint"] = metadata["evidence_fingerprint"]

    def mark_grammar_encounter(self, key: str, **values: Any) -> dict[str, Any] | None:
        self.marked.append({"key": key, **values})
        return dict(self.point)


def test_current_grammar_explanation_cache_skips_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = [
        {
            "kind": "correction",
            "id": 17,
            "original_fragment": "買うておきます",
            "replacement": "買っておきます",
            "reason_zh": "て形错误",
            "created_at": "2026-08-08T12:00:00Z",
        }
    ]
    fingerprint, _ = main._grammar_evidence_fingerprint(evidence)
    repository = GrammarExplanationRepository(
        prompt_version=main.GRAMMAR_EXPLANATION_PROMPT_VERSION,
        evidence_fingerprint=fingerprint,
        evidence=evidence,
    )

    class FailingLLM:
        def reply(self, messages: list[dict[str, str]], **options: Any) -> str:
            raise AssertionError("a current explanation must not call the model")

    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "llm_service", lambda: FailingLLM())

    result = main.get_grammar("verb-te-oku")

    assert result["explanation"] == "已有讲解"
    assert repository.saved is None
    assert repository.marked == []


@pytest.mark.parametrize(
    ("cached_version", "cached_fingerprint"),
    [
        ("grammar-explanation-v1", "current-fingerprint"),
        (main.GRAMMAR_EXPLANATION_PROMPT_VERSION, "stale-fingerprint"),
    ],
)
def test_stale_grammar_cache_regenerates_and_keeps_questions_distinct_from_mistakes(
    monkeypatch: pytest.MonkeyPatch,
    cached_version: str,
    cached_fingerprint: str,
) -> None:
    evidence = [
        {
            "kind": "companion_question",
            "id": 29,
            "question": "这里为什么要用「ておく」？",
            "context_ja": "旅行の前に予約しておきます。",
            "created_at": "2026-08-08T12:00:00Z",
        }
    ]
    current_fingerprint, current_refs = main._grammar_evidence_fingerprint(evidence)
    repository = GrammarExplanationRepository(
        prompt_version=cached_version,
        evidence_fingerprint=(
            current_fingerprint if cached_fingerprint == "current-fingerprint" else cached_fingerprint
        ),
        evidence=evidence,
    )
    prompts: list[list[dict[str, str]]] = []

    class RecordingLLM:
        def reply(self, messages: list[dict[str, str]], **options: Any) -> str:
            prompts.append(messages)
            return "重新生成的讲解"

    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "llm_service", lambda: RecordingLLM())

    result = main.get_grammar("verb-te-oku")

    assert result["explanation"] == "重新生成的讲解"
    assert len(prompts) == 1
    learner_prompt = prompts[0][-1]["content"]
    assert "学习者曾在阅读陪读中明确问过" in learner_prompt
    assert "这里为什么要用「ておく」？" in learner_prompt
    assert "学习者在这个点上实际写错过" not in learner_prompt
    assert repository.saved == {
        "key": "verb-te-oku",
        "content": "重新生成的讲解",
        "prompt_version": main.GRAMMAR_EXPLANATION_PROMPT_VERSION,
        "evidence_fingerprint": current_fingerprint,
        "evidence_refs": current_refs,
    }
