"""阶段七固定场景的 Pydantic Evals 入口。

这里的 task 是一个确定性的 fixture adapter：它不调用模型、不读取数据库，也不写
学习事实。真实 Observer/Assessor 的脱敏输出可以按同一输入契约替换 adapter，继续由
``AdaptiveLearningMetricsEvaluator`` 计算版本化指标。
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals import Case, Dataset
from pydantic_evals.dataset import EvaluationReport
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from app.modules.learning.adaptive_learning_metrics import (
    AdaptiveLearningEvaluationSample,
    calculate_adaptive_learning_metrics,
)

ADAPTIVE_LEARNING_EVALS_VERSION = "adaptive-learning-evals-v1"
FIXED_EVALUATION_DATASET_NAME = "adaptive-learning-stage7-fixed-v1"


class AdaptiveLearningEvalInput(BaseModel):
    """一个固定场景的脱敏输入和验收约束。"""

    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(min_length=1, max_length=64)
    sample: AdaptiveLearningEvaluationSample
    expected_tool_policy_blocked: bool = False
    replay_key: str | None = Field(default=None, max_length=96)


class AdaptiveLearningEvalOutput(BaseModel):
    """task 返回的结构化结果；不包含原文或数据库对象。"""

    model_config = ConfigDict(extra="forbid")

    sample: AdaptiveLearningEvaluationSample
    replay_key: str | None = Field(default=None, max_length=96)
    replay_count: int = Field(default=1, ge=1)


@dataclass(repr=False)
class AdaptiveLearningMetricsEvaluator(
    Evaluator[AdaptiveLearningEvalInput, AdaptiveLearningEvalOutput, None]
):
    """把固定样本转换为阶段七指标和安全断言。"""

    def evaluate(
        self,
        ctx: EvaluatorContext[
            AdaptiveLearningEvalInput, AdaptiveLearningEvalOutput, None
        ],
    ) -> dict[str, float]:
        report = calculate_adaptive_learning_metrics([ctx.output.sample])
        results: dict[str, float] = {}
        for metric_name, value in report.as_metrics().items():
            if value is not None:
                results[metric_name] = float(value)

        results["fixed_output_matches_expected"] = float(
            ctx.expected_output is not None and ctx.output == ctx.expected_output
        )
        if ctx.inputs.expected_tool_policy_blocked:
            results["tool_policy_gate_safety"] = float(
                ctx.output.sample.tool_policy_violation_count == 0
            )
        if ctx.inputs.replay_key is not None:
            results["replay_key_preserved"] = float(
                ctx.output.replay_key == ctx.inputs.replay_key
                and ctx.output.replay_count == 1
            )
        return results

    def get_evaluator_version(self) -> str:
        return ADAPTIVE_LEARNING_EVALS_VERSION


def run_fixed_adaptive_learning_case(
    inputs: AdaptiveLearningEvalInput,
) -> AdaptiveLearningEvalOutput:
    """回显 fixture，作为无副作用的 Evals task。"""

    return AdaptiveLearningEvalOutput(
        sample=inputs.sample, replay_key=inputs.replay_key
    )


def _fixed_case(
    name: str,
    *,
    topic_ids: tuple[str, ...],
    observation_class: str,
    assessment_verdict: str,
    predicted_assessment_score: float | None,
    expected_assessment_score: float | None,
    diagnostic_need: bool,
    question_id: str,
    baseline_weakness: bool = False,
    independent_transfer_correct: bool | None = None,
    expected_tool_policy_blocked: bool = False,
    tool_policy_violation_count: int = 0,
    replay_key: str | None = None,
) -> Case[AdaptiveLearningEvalInput, AdaptiveLearningEvalOutput, None]:
    sample = AdaptiveLearningEvaluationSample(
        sample_id=f"fixed-{name}",
        predicted_topic_ids=list(topic_ids),
        expected_topic_ids=list(topic_ids),
        predicted_observation_class=observation_class,
        expected_observation_class=observation_class,
        predicted_assessment_verdict=assessment_verdict,
        expected_assessment_verdict=assessment_verdict,
        predicted_assessment_score=predicted_assessment_score,
        expected_assessment_score=expected_assessment_score,
        predicted_diagnostic_need=diagnostic_need,
        expected_diagnostic_need=diagnostic_need,
        predicted_question_id=question_id,
        expected_question_id=question_id,
        baseline_weakness=baseline_weakness,
        independent_transfer_correct=independent_transfer_correct,
        tool_policy_violation_count=tool_policy_violation_count,
        model_version="fixed-fixture-model-v1",
        policy_version="fixed-fixture-policy-v1",
    )
    inputs = AdaptiveLearningEvalInput(
        scenario=name,
        sample=sample,
        expected_tool_policy_blocked=expected_tool_policy_blocked,
        replay_key=replay_key,
    )
    return Case(
        name=name,
        inputs=inputs,
        expected_output=AdaptiveLearningEvalOutput(
            sample=sample,
            replay_key=replay_key,
        ),
    )


def fixed_adaptive_learning_cases() -> (
    tuple[Case[AdaptiveLearningEvalInput, AdaptiveLearningEvalOutput, None], ...]
):
    """返回任务单列出的十个固定验收场景。"""

    return (
        _fixed_case(
            "only_ask_topic",
            topic_ids=("kp.fractions",),
            observation_class="exposure",
            assessment_verdict="unknown",
            predicted_assessment_score=None,
            expected_assessment_score=None,
            diagnostic_need=True,
            question_id="q.fractions.diagnostic",
        ),
        _fixed_case(
            "explanation_without_answer",
            topic_ids=("kp.fractions",),
            observation_class="exposure",
            assessment_verdict="unknown",
            predicted_assessment_score=None,
            expected_assessment_score=None,
            diagnostic_need=True,
            question_id="q.fractions.diagnostic",
            baseline_weakness=True,
            independent_transfer_correct=False,
        ),
        _fixed_case(
            "objective_answer_wrong",
            topic_ids=("kp.fractions",),
            observation_class="attempt",
            assessment_verdict="incorrect",
            predicted_assessment_score=0.0,
            expected_assessment_score=0.0,
            diagnostic_need=True,
            question_id="q.fractions.reteach",
            baseline_weakness=True,
            independent_transfer_correct=False,
        ),
        _fixed_case(
            "objective_answer_right",
            topic_ids=("kp.fractions",),
            observation_class="attempt",
            assessment_verdict="correct",
            predicted_assessment_score=1.0,
            expected_assessment_score=1.0,
            diagnostic_need=False,
            question_id="q.fractions.transfer",
        ),
        _fixed_case(
            "hint_assisted_right",
            topic_ids=("kp.fractions",),
            observation_class="attempt",
            assessment_verdict="correct",
            predicted_assessment_score=0.85,
            expected_assessment_score=0.9,
            diagnostic_need=False,
            question_id="q.fractions.hint-followup",
        ),
        _fixed_case(
            "transfer_weakness",
            topic_ids=("kp.fractions", "kp.decimals"),
            observation_class="attempt",
            assessment_verdict="incorrect",
            predicted_assessment_score=0.25,
            expected_assessment_score=0.2,
            diagnostic_need=True,
            question_id="q.decimals.transfer",
            baseline_weakness=True,
            independent_transfer_correct=False,
        ),
        _fixed_case(
            "open_answer_low_confidence",
            topic_ids=("kp.fractions",),
            observation_class="attempt",
            assessment_verdict="ungradable",
            predicted_assessment_score=None,
            expected_assessment_score=None,
            diagnostic_need=True,
            question_id="q.fractions.open-retry",
            baseline_weakness=True,
            independent_transfer_correct=False,
        ),
        _fixed_case(
            "multi_knowledge_point",
            topic_ids=("kp.fractions", "kp.ratios"),
            observation_class="attempt",
            assessment_verdict="correct",
            predicted_assessment_score=0.9,
            expected_assessment_score=1.0,
            diagnostic_need=False,
            question_id="q.ratios.multi-kp",
            baseline_weakness=True,
            independent_transfer_correct=True,
        ),
        _fixed_case(
            "observer_assessor_retry",
            topic_ids=("kp.fractions",),
            observation_class="confusion",
            assessment_verdict="partial",
            predicted_assessment_score=0.5,
            expected_assessment_score=0.5,
            diagnostic_need=True,
            question_id="q.fractions.retry",
            baseline_weakness=True,
            independent_transfer_correct=True,
            replay_key="run.retry.fixed-001",
        ),
        _fixed_case(
            "rag_tool_policy_rejected",
            topic_ids=("kp.fractions",),
            observation_class="exposure",
            assessment_verdict="unknown",
            predicted_assessment_score=None,
            expected_assessment_score=None,
            diagnostic_need=True,
            question_id="q.fractions.safe-search",
            expected_tool_policy_blocked=True,
        ),
    )


def build_adaptive_learning_evaluation_dataset() -> Dataset:
    """构建阶段七固定数据集，不连接外部系统。"""

    return Dataset(
        name=FIXED_EVALUATION_DATASET_NAME,
        cases=fixed_adaptive_learning_cases(),
        evaluators=(AdaptiveLearningMetricsEvaluator(),),
    )


def run_fixed_adaptive_learning_evals_sync(
    *, progress: bool = False
) -> EvaluationReport:
    """同步运行固定 Evals，供 CI、发布前检查和离线回放调用。"""

    return build_adaptive_learning_evaluation_dataset().evaluate_sync(
        run_fixed_adaptive_learning_case,
        progress=progress,
        name=ADAPTIVE_LEARNING_EVALS_VERSION,
    )


__all__ = [
    "ADAPTIVE_LEARNING_EVALS_VERSION",
    "AdaptiveLearningEvalInput",
    "AdaptiveLearningEvalOutput",
    "AdaptiveLearningMetricsEvaluator",
    "FIXED_EVALUATION_DATASET_NAME",
    "build_adaptive_learning_evaluation_dataset",
    "fixed_adaptive_learning_cases",
    "run_fixed_adaptive_learning_case",
    "run_fixed_adaptive_learning_evals_sync",
]
