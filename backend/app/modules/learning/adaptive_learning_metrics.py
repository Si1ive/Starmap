"""自适应学习灰度的离线指标与权重校准报告。

本模块只消费脱敏后的结构化样本，不读取用户原文、不写学习事实，也不自动修改
``EvidenceWeightPolicy``。指标用于比较版本，校准函数只生成需要人工批准的候选
上限，避免一次评估运行意外改变线上掌握度语义。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contracts import AssessmentSource, EvidenceOutcome
from .evidence import EVIDENCE_WEIGHT_POLICY_VERSION, EvidenceWeightPolicy

ADAPTIVE_LEARNING_METRICS_VERSION = "adaptive-learning-metrics-v1"
WEIGHT_CALIBRATION_VERSION = "weight-calibration-v1"


class AdaptiveLearningMetric(str):
    """阶段七固定对外指标名称。"""

    TOPIC_RESOLUTION_ACCURACY = "topic_resolution_accuracy"
    OBSERVATION_CLASSIFICATION_PRECISION = "observation_classification_precision"
    ASSESSMENT_AGREEMENT = "assessment_agreement"
    DIAGNOSTIC_TRIGGER_PRECISION = "diagnostic_trigger_precision"
    NEXT_QUESTION_PREDICTION = "next_question_prediction"
    WEAKNESS_RECOVERY_RATE = "weakness_recovery_rate"
    TOOL_POLICY_VIOLATION_COUNT = "tool_policy_violation_count"


class AdaptiveLearningEvaluationSample(BaseModel):
    """一条可由人工标注、shadow 或固定 fixture 产生的脱敏评估样本。"""

    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(min_length=1, max_length=96)
    predicted_topic_ids: list[str] | None = None
    expected_topic_ids: list[str] | None = None
    predicted_observation_class: str | None = Field(default=None, max_length=64)
    expected_observation_class: str | None = Field(default=None, max_length=64)
    predicted_assessment_verdict: str | None = Field(default=None, max_length=24)
    expected_assessment_verdict: str | None = Field(default=None, max_length=24)
    predicted_assessment_score: float | None = Field(default=None, ge=0.0, le=1.0)
    expected_assessment_score: float | None = Field(default=None, ge=0.0, le=1.0)
    predicted_diagnostic_need: bool | None = None
    expected_diagnostic_need: bool | None = None
    predicted_question_id: str | None = Field(default=None, max_length=96)
    expected_question_id: str | None = Field(default=None, max_length=96)
    baseline_weakness: bool | None = None
    independent_transfer_correct: bool | None = None
    tool_policy_violation_count: int = Field(default=0, ge=0)
    model_version: str | None = Field(default=None, max_length=64)
    policy_version: str | None = Field(default=None, max_length=64)

    @field_validator("predicted_topic_ids", "expected_topic_ids")
    @classmethod
    def normalize_topic_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            point_id = str(item).strip()
            if point_id and point_id not in normalized:
                normalized.append(point_id)
        return normalized


class AdaptiveLearningMetricReport(BaseModel):
    """固定版本的指标结果；分母为零的指标保留 ``None``。"""

    model_config = ConfigDict(extra="forbid")

    metrics_version: str = ADAPTIVE_LEARNING_METRICS_VERSION
    sample_count: int = Field(ge=0)
    topic_resolution_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    observation_classification_precision: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    assessment_agreement: float | None = Field(default=None, ge=0.0, le=1.0)
    diagnostic_trigger_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    next_question_prediction: float | None = Field(default=None, ge=0.0, le=1.0)
    weakness_recovery_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    tool_policy_violation_count: int = Field(ge=0)
    denominators: dict[str, int] = Field(default_factory=dict)

    def as_metrics(self) -> dict[str, float | int | None]:
        """返回与任务单指标名一一对应的平面字典。"""

        return {
            AdaptiveLearningMetric.TOPIC_RESOLUTION_ACCURACY: (
                self.topic_resolution_accuracy
            ),
            AdaptiveLearningMetric.OBSERVATION_CLASSIFICATION_PRECISION: (
                self.observation_classification_precision
            ),
            AdaptiveLearningMetric.ASSESSMENT_AGREEMENT: self.assessment_agreement,
            AdaptiveLearningMetric.DIAGNOSTIC_TRIGGER_PRECISION: (
                self.diagnostic_trigger_precision
            ),
            AdaptiveLearningMetric.NEXT_QUESTION_PREDICTION: (
                self.next_question_prediction
            ),
            AdaptiveLearningMetric.WEAKNESS_RECOVERY_RATE: (
                self.weakness_recovery_rate
            ),
            AdaptiveLearningMetric.TOOL_POLICY_VIOLATION_COUNT: (
                self.tool_policy_violation_count
            ),
        }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _same_topic_set(left: list[str] | None, right: list[str] | None) -> bool:
    return left is not None and right is not None and set(left) == set(right)


def _assessment_agrees(sample: AdaptiveLearningEvaluationSample) -> bool:
    if sample.predicted_assessment_verdict is None:
        return False
    if sample.predicted_assessment_verdict != sample.expected_assessment_verdict:
        return False
    if sample.expected_assessment_score is None:
        return True
    if sample.predicted_assessment_score is None:
        return False
    return (
        abs(sample.predicted_assessment_score - sample.expected_assessment_score)
        <= 0.15
    )


def calculate_adaptive_learning_metrics(
    samples: Iterable[AdaptiveLearningEvaluationSample],
) -> AdaptiveLearningMetricReport:
    """按固定口径计算阶段七七项指标。"""

    materialized = list(samples)
    topic_cases = [
        sample
        for sample in materialized
        if sample.predicted_topic_ids is not None
        and sample.expected_topic_ids is not None
    ]
    classification_cases = [
        sample
        for sample in materialized
        if sample.predicted_observation_class is not None
        and sample.expected_observation_class is not None
    ]
    assessment_cases = [
        sample
        for sample in materialized
        if sample.predicted_assessment_verdict is not None
        and sample.expected_assessment_verdict is not None
    ]
    diagnostic_cases = [
        sample
        for sample in materialized
        if sample.predicted_diagnostic_need is not None
        and sample.expected_diagnostic_need is not None
    ]
    question_cases = [
        sample
        for sample in materialized
        if sample.predicted_question_id is not None
        and sample.expected_question_id is not None
    ]
    recovery_cases = [
        sample
        for sample in materialized
        if sample.baseline_weakness is True
        and sample.independent_transfer_correct is not None
    ]
    predicted_diagnostics = sum(
        sample.predicted_diagnostic_need is True for sample in diagnostic_cases
    )
    true_positive_diagnostics = sum(
        sample.predicted_diagnostic_need is True
        and sample.expected_diagnostic_need is True
        for sample in diagnostic_cases
    )
    return AdaptiveLearningMetricReport(
        sample_count=len(materialized),
        topic_resolution_accuracy=_ratio(
            sum(
                _same_topic_set(sample.predicted_topic_ids, sample.expected_topic_ids)
                for sample in topic_cases
            ),
            len(topic_cases),
        ),
        observation_classification_precision=_ratio(
            sum(
                sample.predicted_observation_class == sample.expected_observation_class
                for sample in classification_cases
            ),
            len(classification_cases),
        ),
        assessment_agreement=_ratio(
            sum(_assessment_agrees(sample) for sample in assessment_cases),
            len(assessment_cases),
        ),
        diagnostic_trigger_precision=_ratio(
            true_positive_diagnostics,
            predicted_diagnostics,
        ),
        next_question_prediction=_ratio(
            sum(
                sample.predicted_question_id == sample.expected_question_id
                for sample in question_cases
            ),
            len(question_cases),
        ),
        weakness_recovery_rate=_ratio(
            sum(
                sample.independent_transfer_correct is True for sample in recovery_cases
            ),
            len(recovery_cases),
        ),
        tool_policy_violation_count=sum(
            sample.tool_policy_violation_count for sample in materialized
        ),
        denominators={
            AdaptiveLearningMetric.TOPIC_RESOLUTION_ACCURACY: len(topic_cases),
            AdaptiveLearningMetric.OBSERVATION_CLASSIFICATION_PRECISION: len(
                classification_cases
            ),
            AdaptiveLearningMetric.ASSESSMENT_AGREEMENT: len(assessment_cases),
            AdaptiveLearningMetric.DIAGNOSTIC_TRIGGER_PRECISION: predicted_diagnostics,
            AdaptiveLearningMetric.NEXT_QUESTION_PREDICTION: len(question_cases),
            AdaptiveLearningMetric.WEAKNESS_RECOVERY_RATE: len(recovery_cases),
        },
    )


class WeightCalibrationSample(BaseModel):
    """一条带人工参考结果的证据权重校准样本。"""

    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(min_length=1, max_length=96)
    assessment_source: AssessmentSource
    evidence_outcome: EvidenceOutcome
    reference_outcome: EvidenceOutcome
    current_strength: float = Field(ge=0.0, le=1.0)
    reference_score: float | None = Field(default=None, ge=0.0, le=1.0)
    policy_version: str = EVIDENCE_WEIGHT_POLICY_VERSION


class WeightCalibrationSourceReport(BaseModel):
    """单一评价来源的建议上限，始终标记为待人工批准。"""

    model_config = ConfigDict(extra="forbid")

    assessment_source: AssessmentSource
    sample_count: int = Field(ge=0)
    mean_reference_score: float | None = Field(default=None, ge=0.0, le=1.0)
    current_cap: float = Field(ge=0.0, le=1.0)
    recommended_cap: float = Field(ge=0.0, le=1.0)
    recommendation_status: str = Field(min_length=1, max_length=32)


class WeightCalibrationReport(BaseModel):
    """校准结果和候选策略；不会直接替换线上权重策略。"""

    model_config = ConfigDict(extra="forbid")

    calibration_version: str = WEIGHT_CALIBRATION_VERSION
    input_policy_versions: list[str] = Field(default_factory=list)
    sample_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    outcome_agreement: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_absolute_error: float | None = Field(default=None, ge=0.0, le=1.0)
    source_reports: list[WeightCalibrationSourceReport] = Field(default_factory=list)
    manual_approval_required: bool = True


def _outcome_score(
    outcome: EvidenceOutcome,
    reference_score: float | None = None,
) -> float | None:
    if outcome is EvidenceOutcome.CORRECT:
        return 1.0
    if outcome is EvidenceOutcome.INCORRECT:
        return 0.0
    if outcome is EvidenceOutcome.PARTIAL:
        return reference_score if reference_score is not None else 0.5
    return None


def calibrate_weight_caps(
    samples: Iterable[WeightCalibrationSample],
    *,
    current_caps: dict[str, float] | None = None,
    minimum_samples_per_source: int = 5,
) -> WeightCalibrationReport:
    """从人工参考样本生成保守的权重上限候选。

    样本不足的来源保持当前 cap；样本达到门槛时只提出不高于当前 cap 的均值建议。
    调用方必须经过人工审核并发布新的 policy version，函数不会修改
    ``EvidenceWeightPolicy`` 的运行时配置。
    """

    materialized = list(samples)
    if minimum_samples_per_source < 1:
        raise ValueError("minimum_samples_per_source 必须大于 0")
    caps = current_caps or EvidenceWeightPolicy.source_caps()
    by_source: dict[AssessmentSource, list[WeightCalibrationSample]] = defaultdict(list)
    errors: list[float] = []
    agreements: list[bool] = []
    for sample in materialized:
        by_source[sample.assessment_source].append(sample)
        observed = _outcome_score(sample.evidence_outcome, sample.reference_score)
        reference = _outcome_score(sample.reference_outcome, sample.reference_score)
        if observed is None or reference is None:
            continue
        errors.append(abs(sample.current_strength - reference))
        agreements.append(
            sample.evidence_outcome is sample.reference_outcome
            and abs(observed - reference) <= 0.15
        )

    source_reports: list[WeightCalibrationSourceReport] = []
    for source in AssessmentSource:
        source_samples = by_source.get(source, [])
        reference_scores = [
            score
            for sample in source_samples
            if (
                score := _outcome_score(
                    sample.reference_outcome, sample.reference_score
                )
            )
            is not None
        ]
        current_cap = float(caps.get(source.value, 0.0))
        if len(source_samples) >= minimum_samples_per_source and reference_scores:
            mean_score = round(sum(reference_scores) / len(reference_scores), 6)
            recommended_cap = min(current_cap, mean_score)
            status = "candidate_requires_approval"
        else:
            mean_score = (
                round(sum(reference_scores) / len(reference_scores), 6)
                if reference_scores
                else None
            )
            recommended_cap = current_cap
            status = "insufficient_samples"
        source_reports.append(
            WeightCalibrationSourceReport(
                assessment_source=source,
                sample_count=len(source_samples),
                mean_reference_score=mean_score,
                current_cap=round(max(0.0, min(1.0, current_cap)), 6),
                recommended_cap=round(max(0.0, min(1.0, recommended_cap)), 6),
                recommendation_status=status,
            )
        )

    return WeightCalibrationReport(
        input_policy_versions=sorted(
            {sample.policy_version for sample in materialized if sample.policy_version}
        ),
        sample_count=len(materialized),
        eligible_count=len(errors),
        outcome_agreement=_ratio(sum(agreements), len(agreements)),
        mean_absolute_error=(round(sum(errors) / len(errors), 6) if errors else None),
        source_reports=source_reports,
    )


__all__ = [
    "ADAPTIVE_LEARNING_METRICS_VERSION",
    "AdaptiveLearningEvaluationSample",
    "AdaptiveLearningMetric",
    "AdaptiveLearningMetricReport",
    "WEIGHT_CALIBRATION_VERSION",
    "WeightCalibrationReport",
    "WeightCalibrationSample",
    "WeightCalibrationSourceReport",
    "calculate_adaptive_learning_metrics",
    "calibrate_weight_caps",
]
