import os
from datetime import datetime, timedelta, timezone

import pytest
from app.config import Settings
from app.db import apply_schema, make_engine
from app.journal import build_journal_messages, generate_journal_reply
from app.llm import LLMReply
from app.prompts import (
    INTERACTIVE_TEACHING_CORE_PROMPT,
    JOURNAL_PROMPT_VERSION,
    JOURNAL_SYSTEM_PROMPT,
)
from app.repository import JOURNAL_TIMELINE_LIMIT, Repository
from sqlalchemy import text


def test_journal_prompt_is_not_built_on_the_teaching_core() -> None:
    """§14.4: every line of the teaching core is wrong here."""

    assert INTERACTIVE_TEACHING_CORE_PROMPT not in JOURNAL_SYSTEM_PROMPT
    assert "N5" not in JOURNAL_SYSTEM_PROMPT
    assert "语法" not in JOURNAL_SYSTEM_PROMPT.split("边界")[0]
    assert JOURNAL_PROMPT_VERSION == "journal-v2"


def test_journal_prompt_asks_for_a_person_before_it_forbids_anything() -> None:
    """The order is the fix from 2026-08-10: an earlier draft led with prohibitions and
    read as a cold thing that is not allowed to speak."""

    wants = JOURNAL_SYSTEM_PROMPT.index("要像个人")
    forbids = JOURNAL_SYSTEM_PROMPT.index("绝对不许编造你自己的经历")
    assert wants < forbids

    assert "可以不同意他" in JOURNAL_SYSTEM_PROMPT
    assert "记得他之前说过的事" in JOURNAL_SYSTEM_PROMPT
    assert "可以很短" in JOURNAL_SYSTEM_PROMPT
    assert "不用小标题、不用列表" in JOURNAL_SYSTEM_PROMPT
    assert "想知道才问" in JOURNAL_SYSTEM_PROMPT


def test_journal_prompt_keeps_the_hard_prohibition_and_the_three_others() -> None:
    assert "我上周也加班到十一点" in JOURNAL_SYSTEM_PROMPT
    assert "不可以有过去" in JOURNAL_SYSTEM_PROMPT
    assert "听起来你感到很沮丧" in JOURNAL_SYSTEM_PROMPT
    assert "不给清单式方案" in JOURNAL_SYSTEM_PROMPT
    assert "不要正能量" in JOURNAL_SYSTEM_PROMPT
    assert "不教日语、不纠错" in JOURNAL_SYSTEM_PROMPT


def test_journal_messages_flatten_history_then_end_with_the_new_entry() -> None:
    messages = build_journal_messages(
        history=[
            {"body": "今天开会开到八点。", "replies": [{"body": "八点，那一天基本没了。"}]},
            {"body": "", "replies": []},
        ],
        body="现在还在加班。",
    )

    assert messages[0] == {"role": "system", "content": JOURNAL_SYSTEM_PROMPT}
    assert messages[1] == {"role": "user", "content": "今天开会开到八点。"}
    assert messages[2] == {"role": "assistant", "content": "八点，那一天基本没了。"}
    # The blank entry contributes nothing rather than an empty turn.
    assert messages[-1] == {"role": "user", "content": "现在还在加班。"}
    assert len(messages) == 4


def test_no_history_means_no_time_note() -> None:
    """A brand-new session has nothing to measure a gap against."""

    messages = build_journal_messages(history=[], body="第一次写。")
    assert messages == [
        {"role": "system", "content": JOURNAL_SYSTEM_PROMPT},
        {"role": "user", "content": "第一次写。"},
    ]


def test_time_note_names_the_real_gap_that_was_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """§14 补记(2026-08-12): the actual bug. Five entries written within two minutes on
    2026-08-10 evening, then this sixth one ~38 hours later — the model answered as if no
    time had passed, because `history` carried no clock at all. Pinned with the real
    timestamps rather than round numbers so a future refactor cannot quietly drop the
    field this depends on (`entry.get("created_at")`) without a test noticing.
    """

    last_entry_at = datetime(2026, 8, 10, 21, 32, 48, tzinfo=timezone(timedelta(hours=8)))
    now = datetime(2026, 8, 12, 11, 54, 37, tzinfo=timezone(timedelta(hours=8)))

    messages = build_journal_messages(
        history=[{"body": "今天开会开到八点。", "replies": [], "created_at": last_entry_at}],
        body="又是加班的一天。",
        now=now,
    )

    note = messages[-2]
    assert note["role"] == "system"
    assert "上一条是前天写的" in note["content"]
    assert "08月12日 11:54" in note["content"]
    # It is calibration for the model, not a script — must not tell it to recite the gap.
    assert "原样念出来" in note["content"]
    assert messages[-1] == {"role": "user", "content": "又是加班的一天。"}


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (30, "刚才"),
        (5 * 60, "5 分钟前"),
        (3 * 3_600, "3 小时前"),
        (30 * 3_600, "昨天"),
        (48 * 3_600, "前天"),
        (5 * 86_400, "5 天前"),
        (20 * 86_400, "3 周前"),
        (90 * 86_400, "3 个月前"),
    ],
)
def test_relative_gap_phrasing_covers_minutes_through_months(seconds: int, expected: str) -> None:
    from app.journal import _relative_gap_zh

    assert _relative_gap_zh(seconds) == expected


def test_journal_reply_is_plain_text_with_no_json_contract() -> None:
    """§14.4: a structured envelope would push it toward headings and bullet lists."""

    class RecordingLLM:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def reply_with_metadata(self, messages: list[dict[str, str]], **values: object) -> LLMReply:
            self.calls.append(values)
            return LLMReply("嗯，那确实够烦的。", "dashscope", "qwen3.7-max", ("dashscope",))

    llm = RecordingLLM()
    reply = generate_journal_reply(llm, [{"role": "user", "content": "累"}])  # type: ignore[arg-type]

    assert reply.content == "嗯，那确实够烦的。"
    assert llm.calls[0].get("json_mode") is None
    assert llm.calls[0]["enable_thinking"] is False


def _repository() -> Repository:
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")
    engine = make_engine(Settings(database_url=database_url))
    apply_schema(engine)
    return Repository(engine)


@pytest.mark.integration
def test_journal_timeline_groups_replies_and_delete_cascades() -> None:
    repository = _repository()
    entry = repository.add_journal_entry("同事又把活推过来了。")
    entry_id = int(entry["id"])
    try:
        repository.add_journal_reply(
            entry_id,
            "又是他。",
            provider="dashscope",
            model="qwen3.7-max",
            prompt_version=JOURNAL_PROMPT_VERSION,
        )
        repository.add_journal_reply(entry_id, "第二次回应。")

        timeline = repository.journal_timeline()
        mine = next(item for item in timeline if int(item["id"]) == entry_id)
        assert [reply["body"] for reply in mine["replies"]] == ["又是他。", "第二次回应。"]
        assert mine["replies"][0]["prompt_version"] == JOURNAL_PROMPT_VERSION

        updated = repository.update_journal_entry(entry_id, "同事又把活推过来了，第三次。")
        assert updated is not None
        assert updated["body"].endswith("第三次。")

        assert repository.delete_journal_entry(entry_id) is True
        with repository.engine.connect() as connection:
            left = connection.execute(
                text("SELECT count(*) FROM journal_reply WHERE entry_id = :id"),
                {"id": entry_id},
            ).scalar_one()
        # Hard delete (§13.7): the replies go with it, nothing is merely hidden.
        assert left == 0
        assert repository.delete_journal_entry(entry_id) is False
    finally:
        repository.delete_journal_entry(entry_id)


@pytest.mark.integration
def test_journal_writes_produce_no_learning_event_and_no_decision_trace() -> None:
    """§14.3 is the whole point of the feature, so it gets a test rather than a comment.

    If a future change wires the journal into the learning side, this fails.
    """

    repository = _repository()
    with repository.engine.connect() as connection:
        events_before = connection.execute(text("SELECT count(*) FROM learning_event")).scalar_one()
        traces_before = connection.execute(text("SELECT count(*) FROM decision_trace")).scalar_one()

    entry = repository.add_journal_entry("今天不想学。")
    entry_id = int(entry["id"])
    try:
        repository.add_journal_reply(entry_id, "那就不学。")
        with repository.engine.connect() as connection:
            events_after = connection.execute(text("SELECT count(*) FROM learning_event")).scalar_one()
            traces_after = connection.execute(text("SELECT count(*) FROM decision_trace")).scalar_one()
        assert events_after == events_before
        assert traces_after == traces_before
    finally:
        repository.delete_journal_entry(entry_id)


@pytest.mark.integration
def test_journal_timeline_is_bounded_so_opening_it_never_gets_slower() -> None:
    """§14.2 / §5.17: one interaction must not cost more as the history grows."""

    repository = _repository()
    created: list[int] = []
    try:
        for index in range(JOURNAL_TIMELINE_LIMIT + 3):
            created.append(int(repository.add_journal_entry(f"第 {index} 条。")["id"]))

        timeline = repository.journal_timeline()
        assert len(timeline) == JOURNAL_TIMELINE_LIMIT
        # Newest kept, and still returned oldest-first for display.
        ids = [int(item["id"]) for item in timeline]
        assert ids == sorted(ids)
        assert ids[-1] == created[-1]
        assert created[0] not in ids
    finally:
        for entry_id in created:
            repository.delete_journal_entry(entry_id)
