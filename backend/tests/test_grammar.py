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


def test_chat_system_prompt_is_trimmed_to_the_supplied_catalogue_subset() -> None:
    # §5.11: the prompt is computed per request from a subset, not the baked-in
    # module constant, once a caller passes one in.
    from app.chat import build_chat_system_prompt

    subset = [("verb-te", "～て", "て形与连接", "N5", "动词变形")]
    prompt = build_chat_system_prompt(subset)

    assert "verb-te = ～て" in prompt
    assert "i-adj-past" not in prompt
    assert "verb-te-iru" not in prompt


def test_companion_system_prompt_is_trimmed_to_the_supplied_catalogue_subset() -> None:
    from app.companion import build_companion_system_prompt

    subset = [("verb-te", "～て", "て形与连接", "N5", "动词变形")]
    prompt = build_companion_system_prompt(subset)

    assert "verb-te = ～て" in prompt
    assert "i-adj-past" not in prompt


def test_learning_event_payload_is_validated_by_kind() -> None:
    from app.learning_events import validated_learning_event_payload
    from pydantic import ValidationError

    correction = validated_learning_event_payload(
        "correction_item",
        {
            "original": "読むています",
            "replacement": "読んでいます",
            "reason_zh": "て形",
            "category": "grammar",
        },
    )
    assert correction["replacement"] == "読んでいます"

    with pytest.raises(ValidationError):
        validated_learning_event_payload(
            "companion_question",
            {"question": "为什么？", "material_id": 1, "segment_id": None, "unexpected": True},
        )
    with pytest.raises(ValidationError):
        validated_learning_event_payload("unknown_kind", {})


def test_m1b_adapter_payloads_are_validated_by_kind() -> None:
    """§5.11 M1-B: vocabulary_saved, vocabulary_reviewed and shadowing_completed join
    the same discriminated union as the M1 kinds — no shared/loose event shape."""
    from app.learning_events import validated_learning_event_payload
    from pydantic import ValidationError

    saved = validated_learning_event_payload(
        "vocabulary_saved", {"word": "検証", "reading": "けんしょう", "meaning": "验证"}
    )
    assert saved == {"word": "検証", "reading": "けんしょう", "meaning": "验证"}

    reviewed = validated_learning_event_payload(
        "vocabulary_reviewed", {"correct": True, "box_before": 1, "box_after": 2}
    )
    assert reviewed == {"correct": True, "box_before": 1, "box_after": 2}

    shadowing = validated_learning_event_payload("shadowing_completed", {"score": 0.83})
    assert shadowing == {"score": 0.83}

    # Privacy boundary (§5.11): audio_path/asr_text are not part of the schema at all,
    # so a caller cannot accidentally smuggle them in even if it tried.
    with pytest.raises(ValidationError):
        validated_learning_event_payload(
            "shadowing_completed", {"score": 0.83, "asr_text": "雨ですね。"}
        )
    with pytest.raises(ValidationError):
        validated_learning_event_payload("vocabulary_saved", {"word": "検証", "meaning": "验证"})


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


class RejectEvidenceRepository:
    """§5.11: reject/unreject return the point projection; the endpoint attaches
    the (now trimmed) evidence list in the same response so the client needs no
    second round trip."""

    def __init__(self, *, point: dict[str, Any] | None, evidence: list[dict[str, Any]]) -> None:
        self.point = point
        self.evidence = evidence
        self.rejected_ids: list[int] = []
        self.unrejected_ids: list[int] = []

    def reject_learning_event(self, event_id: int) -> dict[str, Any] | None:
        self.rejected_ids.append(event_id)
        return dict(self.point) if self.point is not None else None

    def unreject_learning_event(self, event_id: int) -> dict[str, Any] | None:
        self.unrejected_ids.append(event_id)
        return dict(self.point) if self.point is not None else None

    def grammar_evidence(self, key: str) -> list[dict[str, Any]]:
        return self.evidence


def test_reject_grammar_evidence_returns_updated_point_with_trimmed_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = RejectEvidenceRepository(
        point={"id": 1, "key": "verb-te-oku", "status": "encountered", "mistake_count": 0},
        evidence=[],
    )
    monkeypatch.setattr(main, "repository", lambda: repository)

    result = main.reject_grammar_evidence(17)

    assert repository.rejected_ids == [17]
    assert result["status"] == "encountered"
    assert result["evidence"] == []


def test_unreject_grammar_evidence_returns_updated_point_with_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restored_evidence = [{"kind": "correction", "id": 17, "original_fragment": "買うておきます"}]
    repository = RejectEvidenceRepository(
        point={"id": 1, "key": "verb-te-oku", "status": "encountered", "mistake_count": 1},
        evidence=restored_evidence,
    )
    monkeypatch.setattr(main, "repository", lambda: repository)

    result = main.unreject_grammar_evidence(17)

    assert repository.unrejected_ids == [17]
    assert result["evidence"] == restored_evidence


def test_status_update_keeps_detail_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    class StatusRepository:
        def mark_grammar_encounter(self, key: str, **values: Any) -> dict[str, Any]:
            return {"id": 1, "key": key, "status": values["status"]}

        def grammar_evidence(self, key: str) -> list[dict[str, Any]]:
            return [{"kind": "correction", "id": 17, "original_fragment": "買うて"}]

    monkeypatch.setattr(main, "repository", lambda: StatusRepository())

    result = main.set_grammar_status("verb-te", main.GrammarStatusUpdate(status="understood"))

    assert result["status"] == "understood"
    assert result["evidence"][0]["id"] == 17


@pytest.mark.parametrize("endpoint", [main.reject_grammar_evidence, main.unreject_grammar_evidence])
def test_reject_and_unreject_404_on_unknown_event(monkeypatch: pytest.MonkeyPatch, endpoint) -> None:
    repository = RejectEvidenceRepository(point=None, evidence=[])
    monkeypatch.setattr(main, "repository", lambda: repository)

    with pytest.raises(main.HTTPException) as caught:
        endpoint(999)

    assert caught.value.status_code == 404


def test_constructions_in_the_catalogue_have_the_particles_they_require() -> None:
    """§11.11 (resolved 2026-08-10). giving-receiving, verb-passive and verb-causative all
    need に marking the person — 友達にもらう, 先生に褒められた, 子供に食べさせる — and the
    list only had に(time) and に(place). The model explained that に correctly, found no
    matching key, and tagged the nearest one instead, which was simply wrong.

    A prompt guard against picking the nearest worked 1 run in 3. Adding the missing entry
    made it 3 in 3 — the gap was the cause, so the fix belonged in the data.

    Pinned as an invariant rather than as "this key exists": if a later change removes the
    particle while keeping the constructions, the same class of mis-tag comes back.
    """

    keys = {row[0] for row in GRAMMAR_CATALOGUE}
    requires_agent_ni = {"giving-receiving", "verb-passive", "verb-causative"}
    if keys & requires_agent_ni:
        assert "particle-ni-agent" in keys


def test_catalogue_growth_rule_is_documented_next_to_the_data() -> None:
    """The rule that keeps this an index instead of a textbook copy (§12.1, §12.2) has to
    live where someone adding a row will actually read it."""

    import app.grammar_catalogue as catalogue

    assert catalogue.__doc__ is not None
    assert "structurally requires it" in catalogue.__doc__
    assert "never because a" in catalogue.__doc__
