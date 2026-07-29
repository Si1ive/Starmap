"""自适应学习证据的领域契约与旧活动事件兼容适配。

本模块只定义证据语言和安全边界，不负责写数据库或计算掌握度。模型输出可以
提出观察结果，但是否能够进入权威掌握度，必须由服务端根据
``LearningEvidence.is_mastery_evidence`` 再结合来源归属校验决定。
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class EvidenceType(str, Enum):
    """学习证据的行为类型。"""

    EXPOSURE = "exposure"
    SELF_REPORT = "self_report"
    OPEN_RESPONSE = "open_response"
    OBJECTIVE_ASSESSMENT = "objective_assessment"
    HINT_ASSISTED = "hint_assisted"
    TRANSFER = "transfer"
    OBSERVATION = "observation"


class EvidenceOutcome(str, Enum):
    """学习证据可以表达的结果，不等同于掌握度分数。"""

    UNKNOWN = "unknown"
    CORRECT = "correct"
    PARTIAL = "partial"
    INCORRECT = "incorrect"
    UNGRADABLE = "ungradable"


class AssessmentSource(str, Enum):
    """证据的评价或题目来源。"""

    DETERMINISTIC = "deterministic"
    LLM_RUBRIC = "llm_rubric"
    USER_REPORT = "user_report"
    QUESTION_BANK = "question_bank"
    GENERATED_QUESTION = "generated_question"


class ErrorTag(str, Enum):
    """服务端统一的错误标签集合。

    ``answer_mismatch`` 等旧的技术诊断字符串不会被强行伪装成学习错误标签；
    旧事件适配时只保留这里定义的语义标签，原始字符串仍留在旧 payload 中。
    """

    CONCEPT_GAP = "concept_gap"
    MISCONCEPTION = "misconception"
    RETRIEVAL_GAP = "retrieval_gap"
    PROCEDURE_GAP = "procedure_gap"
    TRANSFER_GAP = "transfer_gap"
    CARELESS_ERROR = "careless_error"


class AnswerSource(str, Enum):
    """题目标准答案的来源，和评价器来源分开记录。"""

    QUESTION_BANK = "question_bank"
    GENERATED_QUESTION = "generated_question"
    EXTRACTED = "extracted"
    MANUAL = "manual"
    LLM = "llm"
    USER_PROVIDED = "user_provided"
    RUBRIC = "rubric"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


_MASTERY_OUTCOMES = frozenset(
    {
        EvidenceOutcome.CORRECT,
        EvidenceOutcome.PARTIAL,
        EvidenceOutcome.INCORRECT,
    }
)
_NON_MASTERY_TYPES = frozenset(
    {EvidenceType.EXPOSURE, EvidenceType.OBSERVATION, EvidenceType.SELF_REPORT}
)
_SELF_REPORT_MAX_STRENGTH = 0.25


class EvidenceContext(BaseModel):
    """证据计算所需、但不能由 ``quality`` 字段推断的上下文。

    讲解或观察没有题目答案时显式使用 ``not_applicable``；这样后续策略可以
    区分“没有答案”与“答案来源未知”，也不会把缺字段误当成独立作答。
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
    )

    question_id: str | None = Field(default=None, min_length=1, max_length=128)
    answer_source: AnswerSource = Field(default=AnswerSource.NOT_APPLICABLE)
    hint_levels_used: list[str] = Field(
        default_factory=list,
        max_length=16,
        validation_alias=AliasChoices("hint_levels_used", "hint_levels_used_json"),
    )
    answer_exposed: bool = Field(
        default=False,
        validation_alias=AliasChoices("answer_exposed", "answer_revealed"),
    )

    @field_validator("hint_levels_used")
    @classmethod
    def validate_hint_levels(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            item = item.strip()
            if not item:
                raise ValueError("hint_levels_used 不能包含空标签")
            if item in normalized:
                raise ValueError("hint_levels_used 不能重复")
            normalized.append(item)
        return normalized


class LearningEvidence(BaseModel):
    """结构化学习证据契约。

    该模型故意不提供 ``mastery_score``、``mastery`` 或任意权重写入字段，且
    禁止未知字段。模型只能输出证据事实；掌握度由后续领域投影服务计算。
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
    )

    source_id: str = Field(..., min_length=1, max_length=96)
    source_type: str = Field(default="learning_activity", min_length=1, max_length=32)
    evidence_id: str | None = Field(default=None, min_length=1, max_length=96)
    evidence_type: EvidenceType = Field(...)
    evidence_outcome: EvidenceOutcome = Field(
        ...,
        validation_alias=AliasChoices("evidence_outcome", "outcome"),
    )
    assessment_source: AssessmentSource | None = Field(default=None)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    assessment_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    model_version: str | None = Field(default=None, min_length=1, max_length=64)
    error_tags: list[ErrorTag] = Field(
        default_factory=list,
        max_length=6,
        validation_alias=AliasChoices("error_tags", "error_types"),
    )
    knowledge_point_ids: list[str] = Field(
        default_factory=list,
        max_length=64,
        validation_alias=AliasChoices(
            "knowledge_point_ids", "knowledge_point_ids_json"
        ),
    )
    knowledge_point_coverage: dict[str, float] = Field(
        default_factory=dict,
        validation_alias=AliasChoices(
            "knowledge_point_coverage", "knowledge_point_coverage_json"
        ),
    )
    context: EvidenceContext = Field(
        default_factory=EvidenceContext,
        validation_alias=AliasChoices("context", "evidence_context"),
    )

    @field_validator("source_id", "source_type", "evidence_id", "model_version")
    @classmethod
    def strip_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("证据标识不能是空白字符串")
        return normalized

    @field_validator("knowledge_point_ids")
    @classmethod
    def validate_knowledge_point_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            item = item.strip()
            if not item:
                raise ValueError("knowledge_point_ids 不能包含空白标识")
            if item in normalized:
                raise ValueError("同一条证据不能重复携带知识点 ID")
            normalized.append(item)
        return normalized

    @field_validator("knowledge_point_coverage")
    @classmethod
    def validate_coverage_values(cls, value: dict[str, float]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key, weight in value.items():
            key = str(key).strip()
            if not key:
                raise ValueError("knowledge_point_coverage 不能包含空白知识点 ID")
            if not 0.0 < weight <= 1.0:
                raise ValueError("知识点 coverage 必须大于 0 且不超过 1")
            normalized[key] = weight
        return normalized

    @model_validator(mode="after")
    def validate_contract(self) -> "LearningEvidence":
        if self.evidence_id is None:
            object.__setattr__(self, "evidence_id", self.source_id)

        if self.assessment_confidence is None:
            object.__setattr__(self, "assessment_confidence", self.confidence)
        elif self.confidence not in (0.0, self.assessment_confidence):
            raise ValueError("confidence 与 assessment_confidence 必须一致")
        else:
            object.__setattr__(self, "confidence", self.assessment_confidence)

        ids = self.knowledge_point_ids
        coverage = self.knowledge_point_coverage
        if not ids:
            if coverage:
                raise ValueError("没有知识点 ID 时不能提供 knowledge_point_coverage")
        elif len(ids) == 1:
            point_id = ids[0]
            if not coverage:
                object.__setattr__(self, "knowledge_point_coverage", {point_id: 1.0})
            elif set(coverage) != {point_id} or not _approximately_one(
                coverage[point_id]
            ):
                raise ValueError("单知识点证据的 coverage 必须为 1")
        else:
            if set(coverage) != set(ids):
                raise ValueError("多知识点证据必须为每个知识点提供 coverage")
            if not _approximately_one(sum(coverage.values())):
                raise ValueError("多知识点证据的 coverage 总和必须为 1")

        if self.evidence_type in {
            EvidenceType.EXPOSURE,
            EvidenceType.OBSERVATION,
        }:
            if self.evidence_outcome is not EvidenceOutcome.UNKNOWN:
                raise ValueError(
                    "exposure/observation 不能携带 correct/partial/incorrect verdict"
                )
            if self.evidence_strength != 0.0:
                raise ValueError("exposure/observation 的 evidence_strength 必须为 0")

        if self.evidence_type is EvidenceType.SELF_REPORT:
            if self.assessment_source is not AssessmentSource.USER_REPORT:
                raise ValueError("self_report 的 assessment_source 必须是 user_report")
            if self.evidence_outcome not in {
                EvidenceOutcome.UNKNOWN,
                EvidenceOutcome.UNGRADABLE,
            }:
                raise ValueError(
                    "用户自我声明不能产生 correct/partial/incorrect verdict"
                )
            if self.evidence_strength > _SELF_REPORT_MAX_STRENGTH:
                raise ValueError("用户自我声明不能产生强评分证据")

        if (
            self.assessment_source is AssessmentSource.USER_REPORT
            and self.evidence_type is not EvidenceType.SELF_REPORT
        ):
            raise ValueError("user_report 只能用于 self_report 证据")

        if (
            self.evidence_type is EvidenceType.HINT_ASSISTED
            and not self.context.hint_levels_used
        ):
            raise ValueError("hint_assisted 必须记录至少一个提示级别")

        if (
            self.evidence_type not in _NON_MASTERY_TYPES
            and self.evidence_outcome in _MASTERY_OUTCOMES
        ):
            if self.assessment_source is None:
                raise ValueError("带 verdict 的证据必须声明 assessment_source")

        return self

    @property
    def outcome(self) -> EvidenceOutcome:
        """兼容调用方使用的简短结果名称。"""

        return self.evidence_outcome

    @property
    def idempotency_key(self) -> str:
        """同一来源重放时使用的稳定键，不接受模型自定义。"""

        return f"{self.source_type}:{self.source_id}:{self.evidence_id}"

    @property
    def is_mastery_evidence(self) -> bool:
        """判断证据是否具备进入权威掌握度投影的基本资格。

        这不是掌握度计算，也不替代 EvidenceGate 的来源归属检查；它只是把
        exposure、observation、自我声明和缺少知识点/权重的记录挡在投影边界外。
        """

        return bool(
            self.evidence_type not in _NON_MASTERY_TYPES
            and self.evidence_outcome in _MASTERY_OUTCOMES
            and self.assessment_source
            in {
                AssessmentSource.DETERMINISTIC,
                AssessmentSource.LLM_RUBRIC,
                AssessmentSource.QUESTION_BANK,
                AssessmentSource.GENERATED_QUESTION,
            }
            and self.evidence_strength > 0.0
            and self.knowledge_point_coverage
        )

    def to_payload(self) -> dict[str, Any]:
        """生成可放入 JSON 审计载荷的稳定字段。"""

        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def from_legacy_activity_event(
        cls, event: Mapping[str, Any] | Any
    ) -> "LearningEvidence":
        """把现有三类学习活动事件归一化为新契约。

        兼容读取只读取旧列和 ``payload_json``，不会修改历史行。尤其是旧讲解
        事件的 ``quality`` 有展示/轨迹语义，但没有 verdict，因此明确映射为
        ``exposure + unknown + strength=0``，永远不成为掌握度证据。
        """

        event_type = str(_read(event, "event_type", "") or "").strip()
        source_id = _read(event, "source_id")
        source_type = str(
            _read(event, "source_type", "learning_activity") or "learning_activity"
        )
        payload = _read(event, "payload_json", {})
        payload = payload if isinstance(payload, Mapping) else {}

        nested = payload.get("learning_evidence") or payload.get("evidence")
        if isinstance(nested, Mapping):
            normalized = dict(nested)
            normalized.setdefault("source_id", source_id)
            normalized.setdefault("source_type", source_type)
            return cls.model_validate(normalized)

        column_evidence_type = _read(event, "evidence_type")
        column_evidence_outcome = _read(event, "evidence_outcome")
        if column_evidence_type is not None and column_evidence_outcome is not None:
            if not source_id:
                return cls(
                    source_id=source_id,
                    source_type=source_type,
                    evidence_type=column_evidence_type,
                    evidence_outcome=column_evidence_outcome,
                )
            column_knowledge_point_ids = _deduplicate_strings(
                _read(event, "knowledge_point_ids_json", None) or []
            )
            column_coverage = _read(event, "knowledge_point_coverage_json", None)
            if not isinstance(column_coverage, Mapping):
                column_coverage = _legacy_coverage(payload, column_knowledge_point_ids)
            raw_confidence = _read(event, "assessment_confidence")
            normalized_confidence = (
                float(raw_confidence) if raw_confidence is not None else 0.0
            )
            return cls(
                source_id=str(source_id),
                source_type=source_type,
                evidence_type=column_evidence_type,
                evidence_outcome=column_evidence_outcome,
                assessment_source=_read(event, "assessment_source"),
                confidence=normalized_confidence,
                assessment_confidence=normalized_confidence,
                evidence_strength=float(_read(event, "evidence_strength", 0.0) or 0.0),
                model_version=_read(event, "model_version"),
                error_tags=_known_error_tags(payload.get("error_types") or []),
                knowledge_point_ids=column_knowledge_point_ids,
                knowledge_point_coverage=dict(column_coverage),
                context=EvidenceContext(
                    question_id=_text(
                        payload.get("question_id") or payload.get("practice_item_id")
                    ),
                    answer_source=_answer_source(payload.get("answer_source")),
                    hint_levels_used=list(payload.get("hint_levels_used") or []),
                    answer_exposed=bool(
                        payload.get(
                            "answer_exposed", payload.get("answer_revealed", False)
                        )
                    ),
                ),
            )

        is_correct = _read(event, "is_correct")
        outcome = _outcome_from_bool(is_correct)
        question_id = _text(
            payload.get("question_id") or payload.get("practice_item_id")
        )
        answer_source = _answer_source(payload.get("answer_source"))
        hint_levels_used = list(payload.get("hint_levels_used") or [])
        evidence_type = EvidenceType.OBSERVATION
        assessment_source: AssessmentSource | None = None
        evidence_strength = 0.0

        if event_type == "agent_explanation_completed":
            # 旧 quality（当前为 0.35）不能被解释为掌握度贡献。
            evidence_type = EvidenceType.EXPOSURE
            outcome = EvidenceOutcome.UNKNOWN
            answer_source = AnswerSource.NOT_APPLICABLE
        elif event_type in {"practice_answer_graded", "agent_grade_confirmed"}:
            evidence_type = (
                EvidenceType.HINT_ASSISTED
                if hint_levels_used
                else EvidenceType.OBJECTIVE_ASSESSMENT
            )
            assessment_source = AssessmentSource.DETERMINISTIC
            evidence_strength = 1.0 if outcome in _MASTERY_OUTCOMES else 0.0
        else:
            # 不认识的历史活动只保留为无 verdict 的观察，避免一次兼容读取
            # 意外生成权威掌握度。
            outcome = EvidenceOutcome.UNKNOWN

        knowledge_point_ids = _deduplicate_strings(
            _read(event, "knowledge_point_ids_json", None) or []
        )
        knowledge_point_coverage = _legacy_coverage(payload, knowledge_point_ids)
        if not source_id:
            # 交给 Pydantic 处理 required source_id，确保所有入口拥有一致错误。
            return cls(
                source_id=source_id,
                source_type=source_type,
                evidence_type=evidence_type,
                evidence_outcome=outcome,
            )
        return cls(
            source_id=str(source_id),
            source_type=source_type,
            evidence_type=evidence_type,
            evidence_outcome=outcome,
            assessment_source=assessment_source,
            confidence=1.0 if outcome in _MASTERY_OUTCOMES else 0.0,
            assessment_confidence=1.0 if outcome in _MASTERY_OUTCOMES else 0.0,
            evidence_strength=evidence_strength,
            error_tags=_known_error_tags(payload.get("error_types") or []),
            knowledge_point_ids=knowledge_point_ids,
            knowledge_point_coverage=knowledge_point_coverage,
            context=EvidenceContext(
                question_id=question_id,
                answer_source=answer_source,
                hint_levels_used=hint_levels_used,
                answer_exposed=bool(
                    payload.get("answer_exposed", payload.get("answer_revealed", False))
                ),
            ),
        )


# 这些别名让后续 Observer/Assessor 可以使用更具体的命名，同时保持一个权威
# Pydantic 定义，避免不同 workflow 各自演进出相似但不兼容的 evidence schema。
EvidenceRecord = LearningEvidence
LearningEvidenceContract = LearningEvidence
LearningErrorTag = ErrorTag


def learning_evidence_from_activity_event(
    event: Mapping[str, Any] | Any,
) -> LearningEvidence:
    """模块函数形式的旧事件适配入口。"""

    return LearningEvidence.from_legacy_activity_event(event)


def _approximately_one(value: float) -> bool:
    return abs(value - 1.0) <= 1e-6


def _read(value: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _outcome_from_bool(value: Any) -> EvidenceOutcome:
    if value is True:
        return EvidenceOutcome.CORRECT
    if value is False:
        return EvidenceOutcome.INCORRECT
    return EvidenceOutcome.UNKNOWN


def _answer_source(value: Any) -> AnswerSource:
    normalized = _text(value)
    if not normalized:
        return AnswerSource.UNKNOWN
    try:
        return AnswerSource(normalized)
    except ValueError:
        # 老题目可能使用 extracted/manual/llm 之外的字符串；兼容读取不
        # 让它获得更高可信度，只降级为 unknown。
        return AnswerSource.UNKNOWN


def _deduplicate_strings(values: Any) -> list[str]:
    result: list[str] = []
    if not isinstance(values, (list, tuple, set)):
        return result
    for value in values:
        normalized = _text(value)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _legacy_coverage(
    payload: Mapping[str, Any], knowledge_point_ids: list[str]
) -> dict[str, float]:
    """为没有 coverage 列的旧事件提供可解释的兼容权重。"""

    raw = payload.get("knowledge_point_coverage") or payload.get(
        "knowledge_point_coverage_json"
    )
    if isinstance(raw, Mapping):
        return {str(key): float(value) for key, value in raw.items()}
    if len(knowledge_point_ids) <= 1:
        return {knowledge_point_ids[0]: 1.0} if knowledge_point_ids else {}
    weight = 1.0 / len(knowledge_point_ids)
    return {point_id: weight for point_id in knowledge_point_ids}


def _known_error_tags(values: Any) -> list[ErrorTag]:
    """只保留统一契约中的错误标签，旧技术诊断仍保留在 payload 中。"""
    known = {item.value for item in ErrorTag}
    return [
        ErrorTag(normalized)
        for value in values
        if (normalized := _text(value)) in known
    ]


__all__ = [
    "AnswerSource",
    "AssessmentSource",
    "ErrorTag",
    "EvidenceContext",
    "EvidenceOutcome",
    "EvidenceRecord",
    "EvidenceType",
    "LearningErrorTag",
    "LearningEvidence",
    "LearningEvidenceContract",
    "learning_evidence_from_activity_event",
]
