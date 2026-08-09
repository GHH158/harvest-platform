from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.llm import LLMReply
from app.prompts import INTERACTIVE_TEACHING_CORE_PROMPT
from app.role_blind import (
    ROLE_BLIND_PARTICIPANTS,
    ROLE_BLIND_PROTOCOL_VERSION,
    candidate_role_ids,
    summarize_role_traces,
)
from app.roles import (
    ROLE_DISCLOSURE_ZH,
    ROLE_MANIFEST_VERSION,
    ROLE_PERSPECTIVE_PROMPT_VERSION,
    RoleOutputError,
    build_role_messages,
    generate_role_perspective,
    parse_role_perspective,
    public_role_profiles,
    role_definition,
)


def perspective_json(**updates: Any) -> str:
    payload = {
        "headline_zh": "这句话语法成立，但当前场景下稍显生硬。",
        "analysis_zh": "如果是同事之间的日常回应，换成更短的说法会更自然。",
        "reusable_ja": "そうなんですね。",
        "claim_type": "usage_tendency",
        "focus_tags": ["naturalness", "register"],
        "uncertainty_zh": None,
    }
    payload.update(updates)
    return json.dumps(payload, ensure_ascii=False)


def test_role_catalogue_has_one_host_three_distinct_participants_and_disclosure() -> None:
    profiles = public_role_profiles()

    assert [profile["id"] for profile in profiles] == ["haru", "aoi", "kei", "lin"]
    assert [profile["role_type"] for profile in profiles].count("host") == 1
    assert [profile["role_type"] for profile in profiles].count("participant") == 3
    assert len({profile["lens_zh"] for profile in profiles}) == 4
    assert all(profile["is_fictional"] is True for profile in profiles)
    assert all(profile["disclosure_zh"] == ROLE_DISCLOSURE_ZH for profile in profiles)
    assert all(profile["manifest_version"] == ROLE_MANIFEST_VERSION for profile in profiles)


def test_participant_manifests_have_separate_lenses_and_evidence_whitelists() -> None:
    participants = [role_definition(role_id) for role_id in ("aoi", "kei", "lin")]
    assert all(role is not None for role in participants)
    roles = [role for role in participants if role is not None]

    assert "explicit_relationship_context" in roles[0].allowed_evidence_kinds
    assert "grammar_catalogue" in roles[1].allowed_evidence_kinds
    assert "active_transfer_memory" in roles[2].allowed_evidence_kinds
    assert all("current_task" in role.allowed_evidence_kinds for role in roles)
    assert len({role.core_identity for role in roles}) == 3
    assert len({role.voice for role in roles}) == 3


def test_role_prompts_share_protected_teaching_core_but_not_each_others_identity() -> None:
    prompts: dict[str, str] = {}
    for role_id in ("aoi", "kei", "lin"):
        role = role_definition(role_id)
        assert role is not None
        messages = build_role_messages(
            role,
            sentence_ja="昨日、映画を見る。",
            question="这句话哪里不自然？",
            context_zh="和同事聊昨天做的事。",
        )
        prompts[role_id] = messages[0]["content"]
        assert prompts[role_id].startswith(INTERACTIVE_TEACHING_CORE_PROMPT)
        assert ROLE_DISCLOSURE_ZH in prompts[role_id]
        assert "人格只影响关注角度和表达方式" in prompts[role_id]
        assert "不得为了显示差异制造观点" in prompts[role_id]
        task = json.loads(messages[1]["content"])
        assert task["sentence_ja"] == "昨日、映画を見る。"
        assert task["context_zh"] == "和同事聊昨天做的事。"

    assert "当代日语的自然听感" in prompts["aoi"]
    assert "语法关系、信息结构" in prompts["kei"]
    assert "中日同形、语序和表达视角" in prompts["lin"]
    assert '"focus_tags":["naturalness"]' in prompts["aoi"]
    assert '"focus_tags":["grammar_structure"]' in prompts["kei"]
    assert '"focus_tags":["chinese_transfer"]' in prompts["lin"]
    assert "不要展开活用规则" in prompts["aoi"]
    assert "只给一个最小对照" in prompts["kei"]
    assert "没有具体迁移来源时不得把问题归因于中文" in prompts["lin"]
    assert all("本视角增量卡片" in prompt for prompt in prompts.values())
    assert "角色名：圭" not in prompts["aoi"]
    assert "角色名：林" not in prompts["kei"]
    assert "角色名：葵" not in prompts["lin"]


def test_host_cannot_be_called_as_a_single_role_preview() -> None:
    host = role_definition("haru")
    assert host is not None

    with pytest.raises(ValueError, match="M3"):
        build_role_messages(host, sentence_ja="雨です。", question="怎么理解？")


def test_role_output_contract_rejects_spoofed_identity_and_unknown_claims() -> None:
    parsed = parse_role_perspective(perspective_json())
    assert parsed.claim_type == "usage_tendency"
    assert parsed.focus_tags == ["naturalness", "register"]

    with pytest.raises(RoleOutputError):
        parse_role_perspective(perspective_json(role_id="aoi"))
    with pytest.raises(RoleOutputError):
        parse_role_perspective(perspective_json(claim_type="absolute_truth"))
    with pytest.raises(RoleOutputError):
        parse_role_perspective(perspective_json(focus_tags=["naturalness", "invented"]))
    with pytest.raises(RoleOutputError):
        parse_role_perspective(perspective_json(claim_type="uncertain", uncertainty_zh=None))
    uncertain = parse_role_perspective(
        perspective_json(claim_type="uncertain", uncertainty_zh="缺少说话双方的关系。")
    )
    assert uncertain.uncertainty_zh == "缺少说话双方的关系。"


def test_format_repair_tracks_the_model_that_produced_the_final_perspective() -> None:
    role = role_definition("aoi")
    assert role is not None

    class MetadataLLM:
        def __init__(self) -> None:
            self.responses = iter(
                [
                    LLMReply("not json", "dashscope", "qwen3.7-max", ("dashscope",)),
                    LLMReply(
                        perspective_json(),
                        "deepseek",
                        "deepseek-v4-flash",
                        ("dashscope", "deepseek"),
                    ),
                ]
            )

        def reply_with_metadata(self, messages: list[dict[str, str]], **options: Any) -> LLMReply:
            return next(self.responses)

    perspective = generate_role_perspective(MetadataLLM(), role, [])  # type: ignore[arg-type]

    assert perspective.decision_context == {
        "model_provider": "deepseek",
        "model_name": "deepseek-v4-flash",
        "prompt_version": ROLE_PERSPECTIVE_PROMPT_VERSION,
        "manifest_version": ROLE_MANIFEST_VERSION,
        "attempted_providers": ["dashscope", "deepseek"],
    }
    assert "_decision_context" not in perspective.model_dump()


def test_role_alignment_mismatch_is_repaired_with_the_roles_own_focus() -> None:
    role = role_definition("kei")
    assert role is not None

    class MisalignedLLM:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, str]]] = []
            self.responses = iter(
                [
                    LLMReply(perspective_json(), "dashscope", "qwen3.7-max", ("dashscope",)),
                    LLMReply(
                        perspective_json(
                            headline_zh="活用结构需要调整。",
                            analysis_zh="見る先变成て形「見て」，再接「いる」。",
                            reusable_ja="今、本を見ています。",
                            focus_tags=["grammar_structure"],
                        ),
                        "dashscope",
                        "qwen3.7-max",
                        ("dashscope",),
                    ),
                ]
            )

        def reply_with_metadata(self, messages: list[dict[str, str]], **options: Any) -> LLMReply:
            self.calls.append(messages)
            return next(self.responses)

    llm = MisalignedLLM()
    perspective = generate_role_perspective(llm, role, [])  # type: ignore[arg-type]

    assert perspective.focus_tags == ["grammar_structure"]
    assert len(llm.calls) == 2
    assert "focus_tags 至少包含 grammar_structure" in llm.calls[1][0]["content"]


def test_two_misaligned_outputs_fail_at_role_alignment() -> None:
    role = role_definition("lin")
    assert role is not None

    class AlwaysMisalignedLLM:
        def __init__(self) -> None:
            self.responses = iter(
                [
                    LLMReply(perspective_json(), "dashscope", "qwen3.7-max", ("dashscope",)),
                    LLMReply(perspective_json(), "dashscope", "qwen3.7-max", ("dashscope",)),
                ]
            )

        def reply_with_metadata(self, messages: list[dict[str, str]], **options: Any) -> LLMReply:
            return next(self.responses)

    with pytest.raises(RoleOutputError) as caught:
        generate_role_perspective(AlwaysMisalignedLLM(), role, [])  # type: ignore[arg-type]

    assert caught.value.failure_stage == "role_alignment"
    assert caught.value.decision_context["prompt_version"] == ROLE_PERSPECTIVE_PROMPT_VERSION


def test_two_invalid_role_outputs_keep_final_route_on_the_contract_error() -> None:
    role = role_definition("kei")
    assert role is not None

    class BrokenLLM:
        def __init__(self) -> None:
            self.responses = iter(
                [
                    LLMReply("bad", "dashscope", "qwen3.7-max", ("dashscope",)),
                    LLMReply("still bad", "deepseek", "deepseek-v4-flash", ("deepseek",)),
                ]
            )

        def reply_with_metadata(self, messages: list[dict[str, str]], **options: Any) -> LLMReply:
            return next(self.responses)

    with pytest.raises(RoleOutputError) as caught:
        generate_role_perspective(BrokenLLM(), role, [])  # type: ignore[arg-type]

    assert caught.value.failure_stage == "parse_contract"
    assert caught.value.decision_context["model_provider"] == "deepseek"
    assert caught.value.decision_context["prompt_version"] == ROLE_PERSPECTIVE_PROMPT_VERSION


def test_blind_regression_set_has_ten_stable_role_neutral_questions() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "role_regression_cases.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert len(cases) == 10
    assert len({case["id"] for case in cases}) == 10
    assert all(set(case) == {"id", "sentence_ja", "question", "context_zh"} for case in cases)
    assert all(case["sentence_ja"].strip() and case["question"].strip() for case in cases)
    assert not any(role_id in json.dumps(cases, ensure_ascii=False) for role_id in ("aoi", "kei", "lin"))


def test_blind_v2_uses_a_stable_fresh_per_case_permutation() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "role_regression_cases.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert ROLE_BLIND_PROTOCOL_VERSION == "m2-blind-v2"
    for case in cases:
        first = candidate_role_ids(case["id"])
        assert first == candidate_role_ids(case["id"])
        assert set(first) == set(ROLE_BLIND_PARTICIPANTS)


def test_blind_trace_summary_rejects_missing_or_stale_prompt_records() -> None:
    complete_rows = [
        {
            "status": "ok",
            "model_provider": "dashscope",
            "prompt_version": ROLE_PERSPECTIVE_PROMPT_VERSION,
            "subject_key": role_id,
        }
        for role_id in ROLE_BLIND_PARTICIPANTS
        for _ in range(10)
    ]

    summary = summarize_role_traces(complete_rows, expected_calls=30)
    stale = summarize_role_traces(
        [*complete_rows[:-1], {**complete_rows[-1], "prompt_version": "role-perspective-v1"}],
        expected_calls=30,
    )

    assert summary["complete"] is True
    assert summary["recorded_traces"] == 30
    assert stale["complete"] is False
    assert any("prompt_version" in issue for issue in stale["issues"])
