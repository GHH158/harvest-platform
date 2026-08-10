from __future__ import annotations

import json
from typing import Any

import pytest
from app import main
from app.chat import (
    CHAT_PROMPT_VERSION,
    CHAT_SYSTEM_PROMPT,
    ChatOutputError,
    assistant_content,
    chat_messages,
    generate_chat_turn,
    parse_chat_turn,
    suppress_follow_up,
    topic_for,
)
from app.llm import LLMReply
from app.prompts import INTERACTIVE_TEACHING_CORE_PROMPT
from fastapi import HTTPException


def model_json(*, correction: dict[str, Any] | None = None) -> str:
    return json.dumps(
        {
            "correction": correction
            or {
                "needed": False,
                "corrected_text": None,
                "summary_zh": None,
                "items": [],
            },
            "reply_ja": "それはいいですね。",
            "follow_up_ja": "どんなところが一番よかったですか？",
        },
        ensure_ascii=False,
    )


def correction_json(*, category: str = "grammar", item_count: int = 1) -> str:
    items = [
        {
            "original": f"映画を見ます{i}",
            "replacement": f"映画を見ました{i}",
            "reason_zh": "已经发生的事情使用过去时。",
            "category": category,
        }
        for i in range(item_count)
    ]
    return model_json(
        correction={
            "needed": True,
            "corrected_text": "昨日、映画を見ました。",
            "summary_zh": "把动词改为过去时。",
            "items": items,
        }
    )


class SequenceLLM:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []
        self.options: list[dict[str, Any]] = []

    def reply(self, messages: list[dict[str, str]], **options: Any) -> str:
        self.calls.append(messages)
        self.options.append(options)
        return self.responses.pop(0)


def test_topics_accept_featured_or_custom_but_not_both() -> None:
    assert topic_for("daily-happy", None) == ("最近、ちょっと嬉しかったこと", "daily-happy")
    assert topic_for(None, "  最近的工作  ") == ("最近的工作", None)
    with pytest.raises(ValueError, match="二选一"):
        topic_for(None, "  ")
    with pytest.raises(ValueError, match="二选一"):
        topic_for("daily-happy", "周末")
    with pytest.raises(ValueError, match="不存在"):
        topic_for("missing", None)


def test_chat_uses_shared_teaching_core_without_losing_json_contract() -> None:
    assert CHAT_SYSTEM_PROMPT.startswith(INTERACTIVE_TEACHING_CORE_PROMPT)
    assert "不要只给孤立词义" in CHAT_SYSTEM_PROMPT
    assert "Return exactly one JSON object" in CHAT_SYSTEM_PROMPT
    assert "Allowed correction categories" in CHAT_SYSTEM_PROMPT
    assert "why the expression fits this context" in CHAT_SYSTEM_PROMPT
    assert "Do not add fixed section headings or change the JSON schema" in CHAT_SYSTEM_PROMPT


def test_valid_turns_decode_correction_and_no_correction() -> None:
    natural = parse_chat_turn(model_json())
    corrected = parse_chat_turn(correction_json())

    assert natural.correction.needed is False
    assert natural.correction.items == []
    assert corrected.correction.corrected_text == "昨日、映画を見ました。"
    assert corrected.correction.items[0].category == "grammar"


@pytest.mark.parametrize(
    "raw",
    [
        correction_json(category="meaning"),
        correction_json(item_count=4),
        model_json(
            correction={
                "needed": True,
                "corrected_text": None,
                "summary_zh": "缺少修正版。",
                "items": [],
            }
        ),
        "not json",
    ],
)
def test_invalid_model_contract_is_rejected(raw: str) -> None:
    with pytest.raises(ChatOutputError):
        parse_chat_turn(raw)


def test_invalid_output_gets_exactly_one_repair_attempt() -> None:
    llm = SequenceLLM("not json", model_json())

    turn = generate_chat_turn(llm, [{"role": "user", "content": "昨日映画を見る"}])

    assert turn.reply_ja == "それはいいですね。"
    assert len(llm.calls) == 2
    assert llm.options == [
        {"enable_thinking": False, "json_mode": True, "max_tokens": 1_200},
        {"enable_thinking": False, "json_mode": True, "max_tokens": 1_200},
    ]
    assert "Repair the supplied model output" in llm.calls[1][0]["content"]
    assert llm.calls[1][1]["content"] == "not json"


def test_repaired_chat_turn_tracks_the_model_that_produced_the_final_contract() -> None:
    class MetadataLLM:
        def __init__(self) -> None:
            self.responses = iter(
                [
                    LLMReply("not json", "dashscope", "qwen3.7-max", ("dashscope",)),
                    LLMReply(model_json(), "deepseek", "deepseek-v4-flash", ("dashscope", "deepseek")),
                ]
            )

        def reply_with_metadata(self, messages: list[dict[str, str]], **options: Any) -> LLMReply:
            return next(self.responses)

    turn = generate_chat_turn(MetadataLLM(), [])  # type: ignore[arg-type]
    turn = suppress_follow_up(turn, [{"role": "assistant", "content": "何ですか？"}])

    assert turn.decision_context == {
        "model_provider": "deepseek",
        "model_name": "deepseek-v4-flash",
        "prompt_version": CHAT_PROMPT_VERSION,
        "attempted_providers": ["dashscope", "deepseek"],
    }


def test_two_invalid_outputs_return_explicit_error() -> None:
    llm = SequenceLLM("not json", "still not json")

    with pytest.raises(ChatOutputError, match="连续两次"):
        generate_chat_turn(llm, [])

    assert len(llm.calls) == 2


def test_context_only_contains_recent_twenty_messages_and_chinese_rule() -> None:
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"message-{index}"}
        for index in range(25)
    ]

    messages = chat_messages(
        topic="週末",
        history=history,
        user_message="我想说周末去了公园",
    )

    assert len(messages) == 22
    assert messages[1]["content"] == "message-5"
    assert messages[-2]["content"] == "message-24"
    assert messages[-1]["content"] == "我想说周末去了公园"
    assert "writes mainly in Chinese" in CHAT_SYSTEM_PROMPT
    assert "- grammar" in messages[0]["content"]


class ChatRepository:
    def __init__(self) -> None:
        self.completed = False
        self.created: dict[str, Any] | None = None
        self.session = {"id": "session-1", "topic": "週末"}

    def grammar_catalogue_for_prompt(self) -> list[tuple[str, str, str, str, str]]:
        return [("verb-te", "～て", "て形与连接", "N5", "动词变形")]

    def create_chat_session(self, **values: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        self.created = values
        session = {"id": values["session_id"], "topic": values["topic"], "starter_id": values["starter_id"]}
        return session, {"id": 1, "role": "assistant", "content": values["assistant_content"]}

    def get_chat_session(self, session_id: str) -> dict[str, str] | None:
        return self.session if session_id == self.session["id"] else None

    def chat_messages(self, session_id: str) -> list[dict[str, str]]:
        return []

    def complete_chat_turn(self, **values: Any):
        self.completed = True
        return (
            {"id": 2, "role": "user", "content": values["user_content"]},
            values["correction"],
            {"id": 3, "role": "assistant", "content": values["assistant_content"]},
        )


def test_session_creation_returns_ai_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = ChatRepository()
    opener = parse_chat_turn(model_json())
    captured: dict[str, Any] = {}

    def turn(**values: Any):
        captured.update(values)
        return opener

    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "_chat_turn", turn)

    result = main.create_chat_session(main.ChatSessionCreate(starter_id="daily-weekend"))

    assert result["session"]["topic"] == "今週末の予定"
    assert result["assistant"]["content"].endswith("どんなところが一番よかったですか？")
    assert captured == {
        "topic": "今週末の予定",
        "history": [],
        "user_message": None,
        "catalogue_subset": repository.grammar_catalogue_for_prompt(),
    }


def test_model_contract_failure_writes_no_partial_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = ChatRepository()

    class BrokenLLM:
        def reply(self, messages: list[dict[str, str]], **options: Any) -> str:
            return "not json"

    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "llm_service", lambda: BrokenLLM())

    with pytest.raises(HTTPException) as caught:
        main.post_chat_message("session-1", main.ChatMessageCreate(message="昨日映画を見る"))

    assert caught.value.status_code == 502
    assert "连续两次" in caught.value.detail
    assert repository.completed is False


def test_legacy_chat_failure_does_not_create_a_partial_session(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = ChatRepository()

    class BrokenLLM:
        def reply(self, messages: list[dict[str, str]], **options: Any) -> str:
            return "not json"

    monkeypatch.setattr(main, "repository", lambda: repository)
    monkeypatch.setattr(main, "llm_service", lambda: BrokenLLM())

    with pytest.raises(HTTPException) as caught:
        main.post_chat(main.ChatRequest(session_id="legacy-new", message="こんにちは"))

    assert caught.value.status_code == 502
    assert repository.completed is False


def test_reply_without_a_follow_up_question_is_accepted() -> None:
    # A required follow-up made every turn end in a question: 18 of 18 replies in real
    # use. The learner never got to simply develop their own point.
    turn = parse_chat_turn(
        json.dumps(
            {
                "correction": {"needed": False, "corrected_text": None, "summary_zh": None, "items": []},
                "reply_ja": "「フレーズ」は決まった言い回しのことですよ。",
                "follow_up_ja": None,
            },
            ensure_ascii=False,
        )
    )

    assert turn.follow_up_ja is None
    assert assistant_content(turn) == "「フレーズ」は決まった言い回しのことですよ。"


def test_blank_follow_up_is_treated_as_absent() -> None:
    turn = parse_chat_turn(
        json.dumps(
            {
                "correction": {"needed": False, "corrected_text": None, "summary_zh": None, "items": []},
                "reply_ja": "なるほどですね。",
                "follow_up_ja": "   ",
            },
            ensure_ascii=False,
        )
    )

    assert turn.follow_up_ja is None
    assert assistant_content(turn) == "なるほどですね。"


def test_follow_up_still_renders_when_the_model_asks_one() -> None:
    turn = parse_chat_turn(model_json())

    assert turn.follow_up_ja == "どんなところが一番よかったですか？"
    assert assistant_content(turn) == "それはいいですね。\n\nどんなところが一番よかったですか？"


def test_follow_up_is_dropped_when_the_previous_turn_already_asked() -> None:
    # Prompt guidance alone did not move the model off asking every turn, so the
    # alternation is enforced in code.
    history = [
        {"role": "user", "content": "村上春樹の小説を読みました"},
        {"role": "assistant", "content": "村上春樹、いいですね。\n\nどの作品を読みましたか？"},
    ]
    turn = parse_chat_turn(model_json())

    trimmed = suppress_follow_up(turn, history)

    assert trimmed.follow_up_ja is None
    assert assistant_content(trimmed) == "それはいいですね。"


def test_follow_up_survives_when_the_previous_turn_did_not_ask() -> None:
    history = [
        {"role": "user", "content": "村上春樹の小説を読みました"},
        {"role": "assistant", "content": "村上春樹、いいですね。とても人気があります。"},
    ]
    turn = parse_chat_turn(model_json())

    assert suppress_follow_up(turn, history).follow_up_ja == "どんなところが一番よかったですか？"


def test_opening_turn_keeps_its_question() -> None:
    turn = parse_chat_turn(model_json())

    assert suppress_follow_up(turn, []).follow_up_ja is not None


def test_per_turn_instruction_is_added_only_after_a_question() -> None:
    asked = chat_messages(
        topic="本",
        history=[{"role": "assistant", "content": "どの作品を読みましたか？"}],
        user_message="村上春樹です",
    )
    # Match the per-turn nudge specifically; the system prompt mentions the field too.
    marker = "Your previous turn already ended with a question"
    assert any(marker in m["content"] for m in asked)

    not_asked = chat_messages(
        topic="本",
        history=[{"role": "assistant", "content": "村上春樹、いいですね。"}],
        user_message="村上春樹です",
    )
    assert not any(marker in m["content"] for m in not_asked)


@pytest.mark.parametrize(
    ("text", "is_question"),
    [
        ("どの作品を読みましたか。", True),   # Japanese questions often end in 。 not ？
        ("どんなところが一番よかったですか？", True),
        ("次は何を読もうかな", True),
        ("村上春樹の小説、いいですね。", False),
        ("次の本が決まったら、ぜひ教えてください。", False),
        ("「小説」は物語やストーリーのことです。", False),
    ],
)
def test_question_detection_is_not_punctuation_only(text: str, is_question: bool) -> None:
    history = [{"role": "assistant", "content": text}]
    turn = parse_chat_turn(model_json())

    assert (suppress_follow_up(turn, history).follow_up_ja is None) is is_question


# --- §5.6 2026-08-10: register moves must be visible, no-op items must not survive ---
#
# Both rules came from reading the 14 real corrections in the live database rather than
# from imagining what could go wrong (§11.9's lesson).


def _turn(items: list[dict[str, Any]], *, needed: bool = True) -> str:
    return json.dumps(
        {
            "correction": {
                "needed": needed,
                "corrected_text": "話したいことが話せません" if needed else None,
                "summary_zh": "可能形の否定を使う" if needed else None,
                "items": items,
            },
            "reply_ja": "そうですね。",
            "follow_up_ja": None,
        }
    )


def test_prompt_forbids_no_op_items_and_silent_register_moves() -> None:
    assert "replacement is identical to the original" in CHAT_SYSTEM_PROMPT
    assert "Never raise or lower register silently" in CHAT_SYSTEM_PROMPT
    assert "same_register_replacement" in CHAT_SYSTEM_PROMPT


def test_an_item_that_changes_nothing_is_dropped() -> None:
    """Real data had exactly this: 「日本人として」→「日本人として」, category=register,
    whose own reason said the phrase was fine. The card read "change X to X"."""

    turn = parse_chat_turn(
        _turn(
            [
                {
                    "original": "日本人として",
                    "replacement": "日本人として",
                    "reason_zh": "这个说法本身没问题",
                    "category": "register",
                    "grammar_key": None,
                },
                {
                    "original": "会議しましょう",
                    "replacement": "Teamsで会議をしましょう",
                    "reason_zh": "手段を加えると具体的",
                    "category": "naturalness",
                    "grammar_key": None,
                },
            ]
        )
    )

    assert [item.original for item in turn.correction.items] == ["会議しましょう"]
    assert turn.correction.needed is True


def test_a_correction_made_only_of_no_op_items_downgrades_instead_of_failing() -> None:
    """§12.5's rule: a model quirk should cost the tag, not the user's turn."""

    turn = parse_chat_turn(
        _turn(
            [
                {
                    "original": "日本人として",
                    "replacement": "日本人として",
                    "reason_zh": "没问题",
                    "category": "register",
                    "grammar_key": None,
                }
            ]
        )
    )

    assert turn.correction.needed is False
    assert turn.correction.items == []
    assert turn.correction.corrected_text is None
    assert turn.correction.summary_zh is None
    # The conversation itself is untouched.
    assert turn.reply_ja == "そうですね。"


def test_a_register_move_carries_the_same_register_version() -> None:
    """The real case: the learner wrote plain form and got polite back, with neither the
    reason nor the summary mentioning it."""

    turn = parse_chat_turn(
        _turn(
            [
                {
                    "original": "話さない",
                    "replacement": "話せません",
                    "same_register_replacement": "話せない",
                    "reason_zh": "需要可能态否定；另外你原句是简体，这里给的是丁宁体",
                    "category": "grammar",
                    "grammar_key": None,
                }
            ]
        )
    )

    item = turn.correction.items[0]
    assert item.replacement == "話せません"
    assert item.same_register_replacement == "話せない"


def test_same_register_version_is_dropped_when_it_says_nothing() -> None:
    for alternative in ("話せません", "   ", None):
        turn = parse_chat_turn(
            _turn(
                [
                    {
                        "original": "話さない",
                        "replacement": "話せません",
                        "same_register_replacement": alternative,
                        "reason_zh": "可能态否定",
                        "category": "grammar",
                        "grammar_key": None,
                    }
                ]
            )
        )
        assert turn.correction.items[0].same_register_replacement is None


def test_grammar_items_get_one_explicit_catalogue_check_before_being_left_null() -> None:
    """§12.5 / A1 (2026-08-10). Real data: 5 grammar-category corrections, 3 tagged. The
    diagnosable miss was 「ないですが」→「お肉は入っていませんが」 — the fix is the ～ている
    point and that key exists in the catalogue, so it should not have been null."""

    assert "look at the form your" in CHAT_SYSTEM_PROMPT
    assert "入っていません" in CHAT_SYSTEM_PROMPT
    # The bar itself is unchanged: over-tagging is still the worse failure (§12.5).
    assert "It does not lower the bar" in CHAT_SYSTEM_PROMPT
    assert "a wrong key" in CHAT_SYSTEM_PROMPT
    assert CHAT_PROMPT_VERSION == "chat-turn-v2"


def test_invented_grammar_keys_are_still_dropped_not_trusted() -> None:
    """Widening when a key *should* be set must not widen what counts as a valid key."""

    turn = parse_chat_turn(
        _turn(
            [
                {
                    "original": "ないですが",
                    "replacement": "お肉は入っていませんが",
                    "reason_zh": "て形＋いる的否定",
                    "category": "grammar",
                    "grammar_key": "verb-te-iru",
                },
                {
                    "original": "煮込み",
                    "replacement": "煮込んであるので",
                    "reason_zh": "状态",
                    "category": "grammar",
                    "grammar_key": "this-key-does-not-exist",
                },
            ]
        )
    )

    assert turn.correction.items[0].grammar_key == "verb-te-iru"
    assert turn.correction.items[1].grammar_key is None
