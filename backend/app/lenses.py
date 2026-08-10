"""Reader question angles (§5.15).

Replaces the pre-filled template that made every companion question the same word
lookup (§11.9). The label, the question text stored in history, and the focus added
to the prompt are defined together here so the client only ever sends an id — three
copies of this mapping is how the wording drifts apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LENS_PROMPT_VERSION = "companion-lens-v1"

LensID = Literal["meaning", "naturalness", "structure", "chinese"]


@dataclass(frozen=True)
class QuestionLens:
    id: LensID
    #: 2026-08-10: reworded from 意思/自然吗/结构/和中文 at the learner's request — those
    #: read as flat category names rather than as something a person would say. The new
    #: wording is colloquial, but §11.9's constraint is unchanged and is the reason none
    #: of them got cuter than this: **the label has to say what you get by tapping it.**
    #: A label you cannot tell apart from the others sends you back to always tapping the
    #: first one, which is the template accident wearing a different hat.
    label_zh: str
    #: Rendered into companion_message. Must read as a natural question a person
    #: could have typed — the history is read by a human, not by the server.
    question_zh: str
    question_with_focus_zh: str
    #: Appended to the turn's user content to aim the answer at this angle.
    focus_zh: str


QUESTION_LENSES: tuple[QuestionLens, ...] = (
    QuestionLens(
        id="meaning",
        label_zh="啥意思？",
        question_zh="这句话是什么意思？",
        question_with_focus_zh="「{focus}」在这里是什么意思？",
        focus_zh="回答意思与实际用法，必要时给一个同类例子。不要展开活用规则或中日对比。",
    ),
    QuestionLens(
        id="naturalness",
        label_zh="怪不怪",
        question_zh="这句话听起来自然吗？语体合适吗？",
        question_with_focus_zh="「{focus}」这样说自然吗？语体合适吗？",
        focus_zh=(
            "只谈听感、语体和说话人意图：在当前关系与场景下它给人的感觉，"
            "以及更自然的落点。语法是否成立与语用是否合适分开说。"
            "语境没有说明上下级或亲疏时，明确指出这一点，不要擅自补齐关系。"
        ),
    ),
    QuestionLens(
        id="structure",
        label_zh="拆开看看",
        question_zh="这句话的语法结构是怎样的？",
        question_with_focus_zh="「{focus}」在这句里的语法结构是怎样的？",
        focus_zh=(
            "只讲决定句意的结构关系：助词的作用、活用与接续、修饰指向、信息重心。"
            "需要对照时只给一个最小对照，不要堆砌术语，也不要展开中日对比。"
        ),
    ),
    QuestionLens(
        id="chinese",
        label_zh="跟中文比",
        question_zh="这句话和中文的说法有什么不同？",
        question_with_focus_zh="「{focus}」和中文的说法有什么不同？",
        focus_zh=(
            "只讲中文母语者会踩的具体差异：同形词的异义、搭配、语序或视角的不同。"
            "必须指出一个具体、可验证的中文直觉；说不出具体来源就直说没有明显差异，"
            "不要凭汉字编故事，也不要把所有问题都归因于中文。"
        ),
    ),
)

LENSES_BY_ID = {lens.id: lens for lens in QUESTION_LENSES}


def lens_by_id(lens_id: str) -> QuestionLens | None:
    return LENSES_BY_ID.get(lens_id.strip().lower())


def render_lens_question(lens: QuestionLens, focus_text: str | None) -> str:
    """The sentence stored in history. Never store the raw lens id (§5.15)."""

    focus = (focus_text or "").strip()
    if not focus:
        return lens.question_zh
    return lens.question_with_focus_zh.format(focus=focus)


def public_lenses() -> list[dict[str, str]]:
    return [{"id": lens.id, "label_zh": lens.label_zh} for lens in QUESTION_LENSES]
