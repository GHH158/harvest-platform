from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

LEARNING_EVENT_SCHEMA_VERSION = "learning-event-v1"


class CorrectionItemPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original: str
    replacement: str
    reason_zh: str
    category: str


class CompanionQuestionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    material_id: int | None
    segment_id: int | None


class CorrectionItemEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["correction_item"]
    payload: CorrectionItemPayload


class CompanionQuestionEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["companion_question"]
    payload: CompanionQuestionPayload


LearningEventDraft = Annotated[
    CorrectionItemEventDraft | CompanionQuestionEventDraft,
    Field(discriminator="kind"),
]

_LEARNING_EVENT_DRAFT_ADAPTER = TypeAdapter(LearningEventDraft)


def validated_learning_event_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a v1 payload through the event kind's discriminated branch.

    The database deliberately keeps payload as JSONB so adding a kind does not
    require widening one shared row. This adapter is the stable application
    boundary that prevents malformed internal writes from becoming replay data.
    """

    event = _LEARNING_EVENT_DRAFT_ADAPTER.validate_python({"kind": kind, "payload": payload})
    return event.payload.model_dump(mode="json")
