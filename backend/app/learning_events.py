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


class VocabularySavedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str
    reading: str | None
    meaning: str


class VocabularyReviewedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correct: bool
    box_before: int
    box_after: int


class ShadowingCompletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float


class CorrectionItemEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["correction_item"]
    payload: CorrectionItemPayload


class CompanionQuestionEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["companion_question"]
    payload: CompanionQuestionPayload


class VocabularySavedEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["vocabulary_saved"]
    payload: VocabularySavedPayload


class VocabularyReviewedEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["vocabulary_reviewed"]
    payload: VocabularyReviewedPayload


class ShadowingCompletedEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["shadowing_completed"]
    payload: ShadowingCompletedPayload


LearningEventDraft = Annotated[
    CorrectionItemEventDraft
    | CompanionQuestionEventDraft
    | VocabularySavedEventDraft
    | VocabularyReviewedEventDraft
    | ShadowingCompletedEventDraft,
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
