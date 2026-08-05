from app.companion import COMPANION_SYSTEM_PROMPT, build_companion_messages
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
