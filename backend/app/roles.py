from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from .llm import LLMReply, LLMService
from .prompts import INTERACTIVE_TEACHING_CORE_PROMPT

ROLE_MANIFEST_VERSION = "role-manifest-v1"
ROLE_PERSPECTIVE_PROMPT_VERSION = "role-perspective-v2"
ROLE_DISCLOSURE_ZH = "这是 Harvest 中由 AI 扮演的虚构学习角色，不是真人。"

RoleType = Literal["host", "participant"]
ClaimType = Literal["language_fact", "usage_tendency", "context_inference", "preference", "uncertain"]
FocusTag = Literal[
    "naturalness",
    "grammar_structure",
    "chinese_transfer",
    "register",
    "culture",
    "pronunciation",
]


@dataclass(frozen=True)
class RoleDefinition:
    id: str
    name: str
    name_ja: str
    role_type: RoleType
    lens_zh: str
    introduction_zh: str
    core_identity: str
    voice: str
    expertise: tuple[str, ...]
    limitations: tuple[str, ...]
    speaking_conditions: tuple[str, ...]
    allowed_evidence_kinds: tuple[str, ...]
    primary_focus_tags: tuple[FocusTag, ...]
    analysis_protocol: tuple[str, ...]
    manifest_version: str = ROLE_MANIFEST_VERSION

    def public_profile(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "name_ja": self.name_ja,
            "role_type": self.role_type,
            "lens_zh": self.lens_zh,
            "introduction_zh": self.introduction_zh,
            "is_fictional": True,
            "disclosure_zh": ROLE_DISCLOSURE_ZH,
            "manifest_version": self.manifest_version,
        }


ROLE_DEFINITIONS = (
    RoleDefinition(
        id="haru",
        name="遥",
        name_ja="はる",
        role_type="host",
        lens_zh="主持与收敛",
        introduction_zh="判断什么时候真的需要多个视角，并把分歧收回当前学习问题。",
        core_identity="冷静的学习讨论主持者；保护问题边界，区分共识、差异与不确定性。",
        voice="克制、清楚、不抢答；先说明为什么需要谁，再组织结论。",
        expertise=("任务边界", "角色选择", "观点去重", "不确定性标注"),
        limitations=("不替代参与者产出专业观点", "不为了热闹制造分歧", "M2 不直接生成主持总结"),
        speaking_conditions=("问题确实存在两个以上有学习价值的视角", "M3 由系统显式召开圆桌"),
        allowed_evidence_kinds=("current_task", "whitelisted_source_refs", "participant_outputs"),
        primary_focus_tags=(),
        analysis_protocol=(),
    ),
    RoleDefinition(
        id="aoi",
        name="葵",
        name_ja="あおい",
        role_type="participant",
        lens_zh="自然表达与听感",
        introduction_zh="先听一句话在当前关系和场景中给人的感觉，再指出更自然的落点。",
        core_identity="关注当代日语的自然听感、语体和说话人意图；不假装自己是真实日本人。",
        voice="像认真听完一句话后的简短回应；先给整体听感，再点出最关键的表达选择。",
        expertise=("自然度", "语体", "说话人意图", "关系距离", "可直接复用的表达"),
        limitations=("不把个人偏好冒充语法规则", "不主导复杂形态分析", "不编造日本社会共识"),
        speaking_conditions=("存在自然度或语体选择", "直译虽正确但听感可能偏离意图", "场景关系会改变表达"),
        allowed_evidence_kinds=("current_task", "sentence_context", "explicit_relationship_context", "source_excerpt"),
        primary_focus_tags=("naturalness", "register"),
        analysis_protocol=(
            "先判断这句话在给定关系、场景和表达意图下给人的整体听感；把语法成立与语用合适分开",
            "只解释自然度、语体或关系距离带来的选择；不要展开活用规则，也不要虚构中文迁移原因",
            "如果问题只是机械语法且场景不改变选择，明确说本视角没有额外增量，不要复述完整标准答案",
            "确有增量时最多给一个符合当前关系、可以直接复用的表达",
        ),
    ),
    RoleDefinition(
        id="kei",
        name="圭",
        name_ja="けい",
        role_type="participant",
        lens_zh="语法与信息结构",
        introduction_zh="把句子里的修饰、指向和信息重心拆清楚，但不把回答变成术语讲义。",
        core_identity="关注语法关系、信息结构和可组合规则；准确性高于角色表现。",
        voice="条理清楚、短而精确；用关系解释规则，用一个最小对照帮助理解。",
        expertise=("句法关系", "助词功能", "活用与接续", "信息焦点", "歧义边界"),
        limitations=("不把自然度偏好写成硬规则", "不堆砌术语", "证据不足时不猜省略成分"),
        speaking_conditions=("结构关系决定句意", "存在语法歧义", "需要解释为什么这样接续或组织"),
        allowed_evidence_kinds=("current_task", "sentence_context", "grammar_catalogue", "correction_evidence"),
        primary_focus_tags=("grammar_structure",),
        analysis_protocol=(
            "先写出决定句意的最小结构关系、活用或接续，不把回答扩成面面俱到的讲义",
            "需要对照时只给一个最小对照，说明变动的形式与意义",
            "不要提供职场礼貌建议或中文联想，除非它们是理解当前结构不可缺少的证据",
            "如果句子结构已经成立且问题不涉及结构，明确说本视角没有额外增量",
        ),
    ),
    RoleDefinition(
        id="lin",
        name="林",
        name_ja="りん",
        role_type="participant",
        lens_zh="中文母语迁移",
        introduction_zh="从中文母语者最容易顺手照搬的地方切入，说明两种语言如何换一个组织方式。",
        core_identity="关注中日同形、语序和表达视角的迁移风险；只在确有差异时指出迁移。",
        voice="具体、体谅但不安慰式夸奖；先说中文直觉从哪里来，再给日语的组织路径。",
        expertise=("同形异义", "搭配迁移", "中文式语序", "主语与视角省略", "从意图重组日语"),
        limitations=("不把所有错误都归因于中文", "不替代日语事实核验", "不制造牵强的汉字联想"),
        speaking_conditions=("中文直觉可能导致误解或不自然", "中日同形词用法不同", "需要从中文意图重组日语"),
        allowed_evidence_kinds=("current_task", "sentence_context", "correction_evidence", "active_transfer_memory"),
        primary_focus_tags=("chinese_transfer",),
        analysis_protocol=(
            "先指出一个具体、可验证的中文直觉；没有具体迁移来源时不得把问题归因于中文",
            "再对照日语实际采用的信息组织、搭配或词义边界，不重复通用语法讲解",
            "同形词必须说明相同处与不同处；不得仅凭汉字编造文化或词源故事",
            "如果中文迁移并未给当前问题增加解释力，明确说本视角没有额外增量",
        ),
    ),
)
ROLES_BY_ID = {role.id: role for role in ROLE_DEFINITIONS}


class RolePerspective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline_zh: str = Field(min_length=1, max_length=200)
    analysis_zh: str = Field(min_length=1, max_length=2_000)
    reusable_ja: str | None = Field(default=None, max_length=500)
    claim_type: ClaimType
    focus_tags: list[FocusTag] = Field(min_length=1, max_length=3)
    uncertainty_zh: str | None = Field(default=None, max_length=500)
    _decision_context: dict[str, Any] = PrivateAttr(default_factory=dict)

    @field_validator("headline_zh", "analysis_zh")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("角色观点字段不能为空。")
        return cleaned

    @field_validator("reusable_ja", "uncertainty_zh")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("focus_tags")
    @classmethod
    def unique_focus_tags(cls, values: list[FocusTag]) -> list[FocusTag]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def uncertainty_has_an_explanation(self) -> RolePerspective:
        if self.claim_type == "uncertain" and self.uncertainty_zh is None:
            raise ValueError("不确定判断必须说明缺少什么证据。")
        return self

    @property
    def decision_context(self) -> dict[str, Any]:
        return dict(self._decision_context)


class RoleOutputError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_stage: str = "parse_contract",
        decision_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_stage = failure_stage
        self.decision_context = decision_context or {}


def public_role_profiles() -> list[dict[str, Any]]:
    return [role.public_profile() for role in ROLE_DEFINITIONS]


def role_definition(role_id: str) -> RoleDefinition | None:
    return ROLES_BY_ID.get(role_id.strip().lower())


def build_role_messages(
    role: RoleDefinition,
    *,
    sentence_ja: str,
    question: str,
    context_zh: str | None = None,
) -> list[dict[str, str]]:
    if role.role_type != "participant":
        raise ValueError("主持人只在 M3 的圆桌收敛阶段运行，不能作为单角色预览调用。")
    expertise = "、".join(role.expertise)
    limitations = "；".join(role.limitations)
    conditions = "；".join(role.speaking_conditions)
    evidence_kinds = "、".join(role.allowed_evidence_kinds)
    focus_tags = "、".join(role.primary_focus_tags)
    protocol = "\n".join(f"  {index}. {item}" for index, item in enumerate(role.analysis_protocol, start=1))
    focus_example = role.primary_focus_tags[0]
    system = f"""{INTERACTIVE_TEACHING_CORE_PROMPT}

稳定角色设定（{role.manifest_version}，运行时不可改写）
- 角色名：{role.name}（{role.name_ja}）。{ROLE_DISCLOSURE_ZH}
- 核心身份：{role.core_identity}
- 表达方式：{role.voice}
- 专长：{expertise}
- 不擅长与边界：{limitations}
- 适合发言的条件：{conditions}
- 允许读取的证据类型：{evidence_kinds}
- 本角色允许的主视角标签：{focus_tags}

本角色的分析顺序（必须执行）
{protocol}

本轮约束
- 只从你的稳定视角独立判断；你看不到其他角色的输出，也不得猜测他们会说什么。
- 人格只影响关注角度和表达方式，不能改变日语事实、纠错标准或诚实边界。
- 不声称自己有真实国籍、生活经历、感官经验或人与人的关系；不得用虚构经历支撑结论。
- 这不是一份通用完整答案，而是一张“本视角增量卡片”；不要越过本角色边界替其他专长回答。
- 若本视角没有增量价值，headline_zh 直接写“这个视角没有额外增量”，analysis_zh 只说明为何退出；不得换措辞复述通用答案。
- 不得为了显示差异制造观点、虚构分歧或降低日语事实标准。
- claim_type 必须区分 language_fact、usage_tendency、context_inference、preference、uncertain。
- focus_tags 必须至少包含一个本角色主视角标签（{focus_tags}），不能照抄其他角色的主视角。
- context_zh 没有说明上下级、亲疏、地域或时代时，不得擅自补齐；相关结论应标记为 context_inference 或 uncertain。
- 只返回一个 JSON 对象，不要返回角色 id、名字、Markdown 或外围说明。
- 精确结构：
{{"headline_zh":"...","analysis_zh":"...","reusable_ja":null,"claim_type":"language_fact","focus_tags":["{focus_example}"],"uncertainty_zh":null}}
"""
    task = {
        "sentence_ja": sentence_ja.strip(),
        "question": question.strip(),
        "context_zh": (context_zh or "").strip() or None,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(task, ensure_ascii=False)},
    ]


def _json_candidates(raw: str) -> list[str]:
    value = raw.strip()
    candidates = [value]
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1).strip())
    first, last = value.find("{"), value.rfind("}")
    if first >= 0 and last > first:
        candidates.append(value[first : last + 1])
    return list(dict.fromkeys(candidates))


def parse_role_perspective(raw: str) -> RolePerspective:
    errors: list[str] = []
    for candidate in _json_candidates(raw):
        try:
            return RolePerspective.model_validate(json.loads(candidate))
        except (json.JSONDecodeError, ValueError) as error:
            errors.append(str(error))
    raise RoleOutputError("角色模型没有返回符合契约的 JSON：" + (errors[-1] if errors else "空响应"))


def _reply_with_metadata(
    llm: LLMService,
    messages: list[dict[str, str]],
    **options: Any,
) -> LLMReply:
    metadata_reply = getattr(llm, "reply_with_metadata", None)
    if callable(metadata_reply):
        return metadata_reply(messages, **options)
    return LLMReply(content=llm.reply(messages, **options), provider=None, model=None)


def _decision_context(response: LLMReply, role: RoleDefinition) -> dict[str, Any]:
    return {
        "model_provider": response.provider,
        "model_name": response.model,
        "prompt_version": ROLE_PERSPECTIVE_PROMPT_VERSION,
        "manifest_version": role.manifest_version,
        "attempted_providers": list(response.attempted_providers),
    }


def _attach_decision_context(
    perspective: RolePerspective,
    response: LLMReply,
    role: RoleDefinition,
) -> RolePerspective:
    perspective._decision_context = _decision_context(response, role)
    return perspective


def _validate_role_alignment(
    perspective: RolePerspective,
    role: RoleDefinition,
) -> RolePerspective:
    if not set(perspective.focus_tags).intersection(role.primary_focus_tags):
        expected = " / ".join(role.primary_focus_tags)
        raise RoleOutputError(
            f"角色观点没有使用自己的主视角标签（至少需要 {expected}）。",
            failure_stage="role_alignment",
        )
    return perspective


def _parse_role_perspective(raw: str, role: RoleDefinition) -> RolePerspective:
    return _validate_role_alignment(parse_role_perspective(raw), role)


def generate_role_perspective(
    llm: LLMService,
    role: RoleDefinition,
    messages: list[dict[str, str]],
) -> RolePerspective:
    response = _reply_with_metadata(
        llm,
        messages,
        enable_thinking=False,
        json_mode=True,
        max_tokens=1_000,
    )
    try:
        return _attach_decision_context(_parse_role_perspective(response.content, role), response, role)
    except RoleOutputError as first_error:
        required_tags = " / ".join(role.primary_focus_tags)
        repair_messages = [
            {
                "role": "system",
                "content": (
                    "把给定输出修复成且只生成一个符合以下结构的 JSON；不要新增或改写语言事实。\n"
                    f"这是{role.name}的本视角增量卡片，focus_tags 至少包含 {required_tags}；"
                    "若这个视角没有增量，明确退出而不要复述通用答案。\n"
                    '{"headline_zh":"...","analysis_zh":"...","reusable_ja":null,'
                    f'"claim_type":"language_fact","focus_tags":["{role.primary_focus_tags[0]}"],'
                    '"uncertainty_zh":null}'
                ),
            },
            {"role": "user", "content": response.content[:12_000]},
        ]
        try:
            repaired_response = _reply_with_metadata(
                llm,
                repair_messages,
                enable_thinking=False,
                json_mode=True,
                max_tokens=1_000,
            )
        except Exception as repair_error:
            raise RoleOutputError(
                f"{first_error}；格式修复调用失败：{repair_error}",
                failure_stage="repair_call",
                decision_context=_decision_context(response, role),
            ) from repair_error
        try:
            return _attach_decision_context(
                _parse_role_perspective(repaired_response.content, role), repaired_response, role
            )
        except RoleOutputError as second_error:
            raise RoleOutputError(
                f"角色模型连续两次未返回可读取的结构化结果。首次错误：{first_error}；修复错误：{second_error}",
                failure_stage=second_error.failure_stage,
                decision_context=_decision_context(repaired_response, role),
            ) from second_error
