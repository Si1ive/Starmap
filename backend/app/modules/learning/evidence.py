"""学习证据门禁和服务端权重策略。

模型、练习服务和 Agent 评分都只能提交事实上下文；进入掌握度前必须经过本模块的
``EvidenceGate`` 和 ``EvidenceWeightPolicy``。门禁负责确认来源边界，权重策略负责
把证据类型、答案可信度、提示和知识点 coverage 转成可回放的服务端权重。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

from .contracts import (
    AnswerSource,
    AssessmentSource,
    ErrorTag,
    EvidenceOutcome,
    EvidenceType,
    LearningEvidence,
)

EVIDENCE_WEIGHT_POLICY_VERSION = "evidence-weight-v1"


class EvidenceGateError(ValueError):
    """证据无法证明属于当前用户或不满足掌握度入口条件。"""


@dataclass(frozen=True, slots=True)
class EvidenceWeight:
    """一次证据经过策略裁剪后的权重快照。"""

    evidence_strength: float
    point_strength: dict[str, float]
    policy_version: str = EVIDENCE_WEIGHT_POLICY_VERSION
    reasons: tuple[str, ...] = ()


class EvidenceGate:
    """校验学习证据的来源归属和最小上下文。

    题目和知识点的权威 ID 必须来自服务端已经验证过的题面快照或
    ``EvaluationBundle``；调用方通过 ``verified_knowledge_point_ids`` 把这份快照
    传入，门禁只允许证据引用其中的知识点，不能让模型凭空扩大覆盖范围。
    """

    _TRUSTED_ANSWER_SOURCES = frozenset(
        {
            AnswerSource.QUESTION_BANK,
            AnswerSource.GENERATED_QUESTION,
            AnswerSource.EXTRACTED,
            AnswerSource.MANUAL,
            AnswerSource.RUBRIC,
            AnswerSource.LLM,
        }
    )

    def validate(
        self,
        evidence: LearningEvidence,
        *,
        owner_user_id: object,
        source_user_id: object,
        source_run_id: str | None = None,
        expected_question_id: str | None = None,
        verified_knowledge_point_ids: Iterable[str] | None = None,
        require_knowledge_point_coverage: bool = True,
    ) -> LearningEvidence:
        """验证证据并原样返回，不修改证据中的任何服务端事实。

        ``owner_user_id`` 来自当前 Session/Run，``source_user_id`` 来自实际事件
        来源。二者不一致时直接拒绝，避免跨用户回链或管理员/模型伪造证据。
        """
        owner = _identity(owner_user_id)
        source = _identity(source_user_id)
        if not owner or not source:
            raise EvidenceGateError("学习证据缺少有效的用户归属")
        if owner != source:
            raise EvidenceGateError("学习证据的来源用户与当前用户不一致")

        if not evidence.evidence_id or not evidence.idempotency_key:
            raise EvidenceGateError("学习证据缺少稳定幂等标识")
        if source_run_id is not None and not str(source_run_id).strip():
            raise EvidenceGateError("学习证据的来源 Run ID 不能是空白")
        if (
            evidence.source_type
            in {
                "agent_grade",
                "agent_discussion",
                "agent_practice",
            }
            and not source_run_id
        ):
            raise EvidenceGateError("Agent 学习证据必须回链来源 Run")

        expected_question = _text(expected_question_id)
        actual_question = _text(evidence.context.question_id)
        if expected_question and actual_question != expected_question:
            raise EvidenceGateError("学习证据引用的题目与服务端题面不一致")

        verified_ids = {
            normalized
            for item in (verified_knowledge_point_ids or ())
            if (normalized := _text(item))
        }
        if verified_ids and not set(evidence.knowledge_point_coverage).issubset(
            verified_ids
        ):
            raise EvidenceGateError("学习证据引用了题面未验证的知识点")

        if (
            evidence.evidence_outcome
            in {
                EvidenceOutcome.CORRECT,
                EvidenceOutcome.PARTIAL,
                EvidenceOutcome.INCORRECT,
            }
            and require_knowledge_point_coverage
            and not evidence.knowledge_point_coverage
        ):
            raise EvidenceGateError("评分证据必须绑定至少一个知识点")

        if evidence.is_mastery_evidence:
            if evidence.context.answer_source not in self._TRUSTED_ANSWER_SOURCES:
                raise EvidenceGateError("评分证据缺少可信标准答案来源")
            if (
                evidence.assessment_source is AssessmentSource.LLM_RUBRIC
                and not evidence.model_version
            ):
                raise EvidenceGateError("rubric 评分证据缺少模型版本")
            if evidence.assessment_source is AssessmentSource.GENERATED_QUESTION:
                if evidence.context.answer_source not in {
                    AnswerSource.GENERATED_QUESTION,
                    AnswerSource.LLM,
                }:
                    raise EvidenceGateError("模型生成题的答案来源标记不一致")
            if not evidence.knowledge_point_coverage:
                raise EvidenceGateError("评分证据必须绑定至少一个知识点")
        return evidence


class EvidenceWeightPolicy:
    """把证据上下文转换为服务端可解释权重。

    ``suggested_weight`` 只是调用方携带的不可信建议：它永远会被夹在 ``[0, 1]``
    内并取策略上限，不能提高任何证据的默认可信度。掌握度投影使用
    ``point_strength``，因此多知识点证据会按 coverage 分摊，而不会完整计入每个点。
    """

    _TYPE_BASE = {
        EvidenceType.OBJECTIVE_ASSESSMENT: 1.0,
        EvidenceType.HINT_ASSISTED: 0.7,
        EvidenceType.OPEN_RESPONSE: 0.75,
        EvidenceType.TRANSFER: 0.85,
    }
    _SOURCE_CAP = {
        AssessmentSource.DETERMINISTIC: 1.0,
        AssessmentSource.QUESTION_BANK: 1.0,
        AssessmentSource.LLM_RUBRIC: 0.75,
        AssessmentSource.GENERATED_QUESTION: 0.5,
    }

    def calculate(
        self,
        evidence: LearningEvidence,
        *,
        question_review_status: str | None = None,
        suggested_weight: object | None = None,
    ) -> EvidenceWeight:
        """计算一条证据的总强度和每个知识点的分摊强度。"""
        if not evidence.is_mastery_evidence:
            return EvidenceWeight(
                evidence_strength=0.0,
                point_strength={},
                reasons=("not_mastery_evidence",),
            )

        reasons: list[str] = []
        strength = self._TYPE_BASE.get(evidence.evidence_type, 0.0)
        source_cap = self._SOURCE_CAP.get(evidence.assessment_source, 0.0)
        strength = min(strength, source_cap)

        confidence = evidence.assessment_confidence
        if confidence is None:
            confidence = evidence.confidence
        confidence = _bounded(confidence)
        strength *= confidence
        if confidence < 1.0:
            reasons.append("assessment_confidence")

        requested_evidence_strength = _optional_float(evidence.evidence_strength)
        if requested_evidence_strength is not None:
            strength = min(strength, _bounded(requested_evidence_strength))
            reasons.append("evidence_strength_capped")

        if evidence.context.hint_levels_used:
            hint_factor = max(0.35, 1.0 - 0.15 * len(evidence.context.hint_levels_used))
            strength *= hint_factor
            reasons.append("hint_assisted")
        if evidence.context.answer_exposed:
            strength *= 0.25
            reasons.append("answer_exposed")

        if evidence.context.answer_source in {
            AnswerSource.LLM,
            AnswerSource.GENERATED_QUESTION,
        }:
            strength = min(
                strength,
                (
                    0.5
                    if evidence.assessment_source is AssessmentSource.GENERATED_QUESTION
                    else 0.75
                ),
            )
            reasons.append("answer_source_not_manual")
        if (
            question_review_status
            and question_review_status != "approved"
            and evidence.assessment_source is AssessmentSource.QUESTION_BANK
        ):
            strength = min(strength, 0.5)
            reasons.append("question_not_approved")

        requested = _optional_float(suggested_weight)
        if requested is not None:
            strength = min(strength, _bounded(requested))
            reasons.append("suggested_weight_capped")

        strength = round(max(0.0, min(1.0, strength)), 6)
        point_strength = {
            point_id: round(strength * coverage, 6)
            for point_id, coverage in evidence.knowledge_point_coverage.items()
        }
        return EvidenceWeight(
            evidence_strength=strength,
            point_strength=point_strength,
            reasons=tuple(reasons),
        )


def build_assessment_evidence(
    *,
    source_id: str,
    source_type: str,
    verdict: str,
    question_id: str,
    knowledge_point_ids: Iterable[str],
    answer_source: object | None = None,
    assessment_source: object | None = None,
    hint_levels_used: Iterable[str] | None = None,
    answer_exposed: bool = False,
    confidence: object | None = None,
    model_version: object | None = None,
    knowledge_point_coverage: object | None = None,
    error_tags: Iterable[object] | None = None,
    evidence_type: object | None = None,
) -> LearningEvidence:
    """从服务端评分结果构建统一证据，不接受 mastery 或 delta 字段。"""
    normalized_answer_source = _enum_value(
        AnswerSource,
        answer_source,
        default=AnswerSource.UNKNOWN,
    )
    normalized_assessment_source = _assessment_source(
        assessment_source,
        answer_source=normalized_answer_source,
    )
    normalized_outcome = _enum_value(EvidenceOutcome, verdict, default=None)
    if normalized_outcome is None:
        raise ValueError(f"不支持的学习证据结果: {verdict}")
    hints = [_text(item) for item in (hint_levels_used or ())]
    hints = [item for item in hints if item]
    normalized_type = _enum_value(
        EvidenceType,
        evidence_type,
        default=(
            EvidenceType.HINT_ASSISTED if hints else EvidenceType.OBJECTIVE_ASSESSMENT
        ),
    )
    point_ids = _dedupe(knowledge_point_ids)
    coverage = knowledge_point_coverage
    if not isinstance(coverage, dict):
        coverage = _equal_coverage(point_ids)
    known_error_tags = [
        item
        for item in (_enum_value_name(value) for value in (error_tags or ()))
        if item in {tag.value for tag in ErrorTag}
    ]
    return LearningEvidence(
        source_id=source_id,
        source_type=source_type,
        evidence_type=normalized_type,
        evidence_outcome=normalized_outcome,
        assessment_source=normalized_assessment_source,
        confidence=_bounded(
            _optional_float(confidence) if confidence is not None else 1.0
        ),
        evidence_strength=(
            1.0
            if normalized_outcome
            in {
                EvidenceOutcome.CORRECT,
                EvidenceOutcome.PARTIAL,
                EvidenceOutcome.INCORRECT,
            }
            else 0.0
        ),
        model_version=_text(model_version),
        error_tags=known_error_tags,
        knowledge_point_ids=point_ids,
        knowledge_point_coverage=coverage,
        context={
            "question_id": question_id,
            "answer_source": normalized_answer_source,
            "hint_levels_used": hints,
            "answer_exposed": bool(answer_exposed),
        },
    )


def finalize_evidence_weight(
    evidence: LearningEvidence,
    *,
    policy: EvidenceWeightPolicy | None = None,
    question_review_status: str | None = None,
    suggested_weight: object | None = None,
) -> tuple[LearningEvidence, EvidenceWeight]:
    """写入活动事实前固化服务端权重；返回不可伪造的证据副本。"""
    weight = (policy or EvidenceWeightPolicy()).calculate(
        evidence,
        question_review_status=question_review_status,
        suggested_weight=suggested_weight,
    )
    return (
        evidence.model_copy(update={"evidence_strength": weight.evidence_strength}),
        weight,
    )


def _assessment_source(
    value: object | None,
    *,
    answer_source: AnswerSource,
) -> AssessmentSource:
    if value is not None:
        if isinstance(value, AssessmentSource):
            return value
        try:
            return AssessmentSource(str(value).strip().lower())
        except ValueError as error:
            raise ValueError(f"不支持的评价来源: {value}") from error
    if answer_source in {AnswerSource.GENERATED_QUESTION}:
        return AssessmentSource.GENERATED_QUESTION
    if answer_source is AnswerSource.QUESTION_BANK:
        return AssessmentSource.QUESTION_BANK
    return AssessmentSource.DETERMINISTIC


def _enum_value(enum_type: Any, value: object | None, *, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip().lower())
    except ValueError:
        return default


def _enum_value_name(value: object) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value).strip().lower()


def _identity(value: object) -> str:
    return str(value or "").strip()


def _text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _dedupe(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = _text(value)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _equal_coverage(point_ids: list[str]) -> dict[str, float]:
    if not point_ids:
        return {}
    weight = 1.0 / len(point_ids)
    return {
        point_id: (1.0 if len(point_ids) == 1 else round(weight, 8))
        for point_id in point_ids
    }


def _optional_float(value: object | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _bounded(value: object | None) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        return 0.0
    return max(0.0, min(1.0, parsed))


__all__ = [
    "EVIDENCE_WEIGHT_POLICY_VERSION",
    "EvidenceGate",
    "EvidenceGateError",
    "EvidenceWeight",
    "EvidenceWeightPolicy",
    "build_assessment_evidence",
    "finalize_evidence_weight",
]
