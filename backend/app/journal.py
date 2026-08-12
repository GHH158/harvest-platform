from __future__ import annotations

from datetime import datetime
from typing import Any

from .llm import LLMReply, LLMService
from .prompts import JOURNAL_PROMPT_VERSION, JOURNAL_SYSTEM_PROMPT

__all__ = ["JOURNAL_PROMPT_VERSION", "build_journal_messages", "generate_journal_reply"]

# §14. This module is the whole of the private journal's model interaction and it
# imports nothing from the learning side on purpose — no grammar catalogue, no
# teaching core, no learning events. The isolation in §14.3 runs both ways, and the
# cheapest way to keep it true is for this file to have no way to reach across.


def _relative_gap_zh(seconds: float) -> str:
    """A human phrase for how long ago the last entry was, not a duration the model is
    meant to echo verbatim — just enough for it to know whether it is still "just now"
    or the conversation has actually gone quiet for a while.
    """

    if seconds < 90:
        return "刚才"
    minutes = seconds / 60
    if minutes < 60:
        return f"{round(minutes)} 分钟前"
    hours = minutes / 60
    if hours < 20:
        return f"{round(hours)} 小时前"
    days = hours / 24
    if days < 1.5:
        return "昨天"
    if days < 2.5:
        return "前天"
    if days < 14:
        return f"{round(days)} 天前"
    weeks = days / 7
    if weeks < 8:
        return f"{round(weeks)} 周前"
    months = days / 30
    return f"{round(months)} 个月前"


def build_journal_messages(
    *,
    history: list[dict[str, Any]],
    body: str,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """`history` is the recent timeline (oldest first), each entry with its replies.

    Continuity is the point: it should remember the colleague and the thing that is
    still unresolved (§14.4). It is bounded to whatever the caller passes, which is
    JOURNAL_TIMELINE_LIMIT — one interaction must not get more expensive as the
    history grows (§5.17).

    §14 补记(2026-08-12): none of this ever told the model what time it actually is.
    Real data caught it — five entries written within two minutes on 2026-08-10
    evening, then a sixth entry ~38 hours later on 2026-08-12 that the model answered
    as though it were still that same evening, because nothing in the prompt said
    otherwise. `history` is a flat list of turns with no clock in it at all, and §14.4's
    "remember what is still unresolved" was implemented as "hand over the whole
    transcript", which is memory without a sense of *when*. Fixed by naming the gap
    since the last entry, so continuity means remembering what happened, not assuming
    no time passed.
    """

    messages: list[dict[str, str]] = [{"role": "system", "content": JOURNAL_SYSTEM_PROMPT}]
    for entry in history:
        entry_body = entry.get("body")
        if isinstance(entry_body, str) and entry_body.strip():
            messages.append({"role": "user", "content": entry_body})
        for reply in entry.get("replies") or []:
            reply_body = reply.get("body")
            if isinstance(reply_body, str) and reply_body.strip():
                messages.append({"role": "assistant", "content": reply_body})
    last_created_at = history[-1].get("created_at") if history else None
    if isinstance(last_created_at, datetime):
        current = now if now is not None else datetime.now(last_created_at.tzinfo)
        gap = _relative_gap_zh((current - last_created_at).total_seconds())
        messages.append(
            {
                "role": "system",
                "content": (
                    f"上一条是{gap}写的,现在是{current:%m月%d日 %H:%M}。"
                    "如果这段时间不短,回应时可以自然带出这种感觉(比如提一句都过去两天了),"
                    "不要接得像是紧接着上一句说的。不要把这条提示原样念出来,也不用每次都报时间。"
                ),
            }
        )
    messages.append({"role": "user", "content": body})
    return messages


def generate_journal_reply(llm: LLMService, messages: list[dict[str, str]]) -> LLMReply:
    """Plain text, no JSON contract, no repair pass.

    Unlike the teaching entries there is nothing to validate here: a reply is just
    what it says. A structured envelope would also push it toward headings and
    bullet lists, which §14.4 explicitly bans — a person does not answer you with a
    schema.
    """

    return llm.reply_with_metadata(messages, enable_thinking=False, max_tokens=1_200)
