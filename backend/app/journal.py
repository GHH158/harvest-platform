from __future__ import annotations

from typing import Any

from .llm import LLMReply, LLMService
from .prompts import JOURNAL_PROMPT_VERSION, JOURNAL_SYSTEM_PROMPT

__all__ = ["JOURNAL_PROMPT_VERSION", "build_journal_messages", "generate_journal_reply"]

# §14. This module is the whole of the private journal's model interaction and it
# imports nothing from the learning side on purpose — no grammar catalogue, no
# teaching core, no learning events. The isolation in §14.3 runs both ways, and the
# cheapest way to keep it true is for this file to have no way to reach across.


def build_journal_messages(
    *,
    history: list[dict[str, Any]],
    body: str,
) -> list[dict[str, str]]:
    """`history` is the recent timeline (oldest first), each entry with its replies.

    Continuity is the point: it should remember the colleague and the thing that is
    still unresolved (§14.4). It is bounded to whatever the caller passes, which is
    JOURNAL_TIMELINE_LIMIT — one interaction must not get more expensive as the
    history grows (§5.17).
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
