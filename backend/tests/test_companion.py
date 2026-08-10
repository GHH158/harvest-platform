import pytest
from app.companion import (
    COMPANION_PROMPT_VERSION,
    COMPANION_SYSTEM_PROMPT,
    CompanionOutputError,
    build_companion_messages,
    generate_companion_turn,
    parse_companion_turn,
)
from app.llm import LLMReply
from app.prompts import INTERACTIVE_TEACHING_CORE_PROMPT


def test_companion_uses_the_shared_teaching_core() -> None:
    assert COMPANION_SYSTEM_PROMPT.startswith(INTERACTIVE_TEACHING_CORE_PROMPT)
    assert "按约 N5 的理解起点" in COMPANION_SYSTEM_PROMPT
    assert "不要只给孤立词义" in COMPANION_SYSTEM_PROMPT
    assert "不要为日语添加括号注音" in COMPANION_SYSTEM_PROMPT
    assert "为什么在当前语境下这样表达" in COMPANION_SYSTEM_PROMPT
    assert "如何组织成可复用的自然日语" in COMPANION_SYSTEM_PROMPT
    assert "不要机械显示三个固定标题" in COMPANION_SYSTEM_PROMPT


def test_companion_prompt_treats_reading_context_as_reference_not_vocabulary_limit() -> None:
    assert "一个词没有出现在当前句或相邻句里,绝不等于它不存在" in COMPANION_SYSTEM_PROMPT
    assert "历史中的助手回答不是权威证据" in COMPANION_SYSTEM_PROMPT
    assert "不得声称查询、核对或引用了《広辞苑》《大辞林》" in COMPANION_SYSTEM_PROMPT
    assert "不得为显得完整而扩展可疑义项" in COMPANION_SYSTEM_PROMPT
    assert "不得只凭汉字拆解推导词义" in COMPANION_SYSTEM_PROMPT
    assert "先给当前句唯一最贴切的含义" in COMPANION_SYSTEM_PROMPT
    assert "不得把直观联想当作历史事实" in COMPANION_SYSTEM_PROMPT


def test_companion_prompt_has_no_local_dictionary_grounding_or_keyword_guard() -> None:
    assert "JMdict" not in COMPANION_SYSTEM_PROMPT
    assert "本地词法提示" not in COMPANION_SYSTEM_PROMPT
    assert "证据校验" not in COMPANION_SYSTEM_PROMPT


def test_companion_messages_include_context_history_and_question_only() -> None:
    messages = build_companion_messages(
        context=[{"idx": 4, "text_ja": "今日は風が強いです。"}],
        history=[{"role": "assistant", "content": "先前的回答"}],
        question="请重新解释「流会」。",
    )

    assert messages[0] == {"role": "system", "content": COMPANION_SYSTEM_PROMPT}
    assert messages[1] == {"role": "assistant", "content": "先前的回答"}
    assert "只作语境参考,不是日语词汇的全集" in messages[-1]["content"]
    assert "今日は風が強いです。" in messages[-1]["content"]
    assert messages[-1]["content"].endswith("用户问题:\n请重新解释「流会」。")
    assert "JMdict" not in messages[-1]["content"]


def test_companion_output_tags_only_known_explicit_grammar_keys() -> None:
    turn = parse_companion_turn(
        '{"answer_markdown":"这里是て形。","grammar_keys":["verb-te","invented","verb-te"]}'
    )

    assert turn.answer_markdown == "这里是て形。"
    assert turn.grammar_keys == ["verb-te"]
    # v2 (2026-08-10): registers what the answer actually taught, because with §5.15's
    # tappable angles the learner never names a point — the old "only what they explicitly
    # asked about" no longer described the entry point.
    assert "本轮回答实质讲解过" in COMPANION_SYSTEM_PROMPT
    assert "使用者往往不点名语法点" in COMPANION_SYSTEM_PROMPT


def test_companion_keeps_the_boundaries_that_stop_passive_appearance_becoming_evidence() -> None:
    """The widened scope must not turn "it was in the sentence" into evidence: §13.2 says
    seeing a structure is not understanding it, and a wrong fact cannot be recomputed away."""

    assert "句中只是出现而本轮并没有讲的点" in COMPANION_SYSTEM_PROMPT
    assert "你主动扩展到别处、不属于这句话的点" in COMPANION_SYSTEM_PROMPT
    assert "使用者问的其实是词义或句意" in COMPANION_SYSTEM_PROMPT
    assert "你没有把握" in COMPANION_SYSTEM_PROMPT
    assert "错误登记比漏登记更糟" in COMPANION_SYSTEM_PROMPT
    assert COMPANION_PROMPT_VERSION == "companion-turn-v2"


def test_companion_output_gets_one_format_repair() -> None:
    class RepairingLLM:
        def __init__(self) -> None:
            self.outputs = iter(["plain answer", '{"answer_markdown":"修好的回答","grammar_keys":[]}'])
            self.calls: list[dict] = []

        def reply(self, messages: list[dict[str, str]], **values: object) -> str:
            self.calls.append(values)
            return next(self.outputs)

    llm = RepairingLLM()
    turn = generate_companion_turn(llm, [{"role": "user", "content": "解释一下"}])  # type: ignore[arg-type]

    assert turn.answer_markdown == "修好的回答"
    assert len(llm.calls) == 2
    assert all(call["json_mode"] is True for call in llm.calls)


def test_repaired_companion_turn_tracks_the_final_model_and_prompt_version() -> None:
    class MetadataLLM:
        def __init__(self) -> None:
            self.responses = iter(
                [
                    LLMReply("plain answer", "dashscope", "qwen3.7-max", ("dashscope",)),
                    LLMReply(
                        '{"answer_markdown":"修好的回答","grammar_keys":[]}',
                        "deepseek",
                        "deepseek-v4-flash",
                        ("dashscope", "deepseek"),
                    ),
                ]
            )

        def reply_with_metadata(self, messages: list[dict[str, str]], **values: object) -> LLMReply:
            return next(self.responses)

    turn = generate_companion_turn(MetadataLLM(), [])  # type: ignore[arg-type]

    assert turn.decision_context == {
        "model_provider": "deepseek",
        "model_name": "deepseek-v4-flash",
        "prompt_version": COMPANION_PROMPT_VERSION,
        "attempted_providers": ["dashscope", "deepseek"],
    }


def test_companion_output_fails_after_one_bad_repair() -> None:
    class BrokenLLM:
        def reply(self, messages: list[dict[str, str]], **values: object) -> str:
            return "still not json"

    with pytest.raises(CompanionOutputError, match="格式修复仍失败"):
        generate_companion_turn(BrokenLLM(), [])  # type: ignore[arg-type]


def test_shared_core_flags_chinese_lookalike_traps() -> None:
    # The learner is a Chinese native: 5 of 13 real corrections were interference
    # errors, the clearest being 中文「随时」used as 日语「随時」. Words they can read
    # are exactly the ones they never look up, so the kernel must volunteer the gap.
    assert "中文母语者" in INTERACTIVE_TEACHING_CORE_PROMPT
    assert "汉字看得懂、用法却不同" in INTERACTIVE_TEACHING_CORE_PROMPT
    assert "只在确实存在差异时给出" in INTERACTIVE_TEACHING_CORE_PROMPT


def test_shared_core_reaches_every_teaching_entrance() -> None:
    from app.chat import CHAT_SYSTEM_PROMPT
    from app.prompts import VOICE_TEACHER_SYSTEM_PROMPT

    for prompt in (COMPANION_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT, VOICE_TEACHER_SYSTEM_PROMPT):
        assert "汉字看得懂、用法却不同" in prompt


def test_shared_core_forbids_decorative_symbols() -> None:
    # §1.5 asks for restraint, and the companion page already styles headings with an
    # accent bar — emoji on top of that is stacked decoration, not hierarchy.
    assert "不使用 emoji 或装饰性符号" in INTERACTIVE_TEACHING_CORE_PROMPT

    from app.chat import CHAT_SYSTEM_PROMPT
    from app.prompts import VOICE_TEACHER_SYSTEM_PROMPT

    for prompt in (COMPANION_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT, VOICE_TEACHER_SYSTEM_PROMPT):
        assert "不使用 emoji" in prompt
