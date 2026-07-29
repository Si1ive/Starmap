from app.modules.learning.adaptive_learning_metrics import (
    AdaptiveLearningEvaluationSample,
    AdaptiveLearningMetric,
    WeightCalibrationSample,
    calculate_adaptive_learning_metrics,
    calibrate_weight_caps,
)
from app.modules.learning.contracts import AssessmentSource, EvidenceOutcome


def test_calculate_adaptive_learning_metrics_uses_explicit_denominators():
    report = calculate_adaptive_learning_metrics(
        [
            AdaptiveLearningEvaluationSample(
                sample_id="topic-1",
                predicted_topic_ids=["kp-1"],
                expected_topic_ids=["kp-1"],
                predicted_observation_class="topic_exposure",
                expected_observation_class="topic_exposure",
                predicted_diagnostic_need=False,
                expected_diagnostic_need=False,
                tool_policy_violation_count=0,
            ),
            AdaptiveLearningEvaluationSample(
                sample_id="diagnostic-1",
                predicted_observation_class="confusion",
                expected_observation_class="topic_exposure",
                predicted_diagnostic_need=True,
                expected_diagnostic_need=False,
                tool_policy_violation_count=1,
            ),
            AdaptiveLearningEvaluationSample(
                sample_id="recovery-1",
                baseline_weakness=True,
                independent_transfer_correct=True,
            ),
        ]
    )

    assert report.sample_count == 3
    assert report.topic_resolution_accuracy == 1.0
    assert report.observation_classification_precision == 0.5
    assert report.diagnostic_trigger_precision == 0.0
    assert report.weakness_recovery_rate == 1.0
    assert report.tool_policy_violation_count == 1
    assert report.denominators[AdaptiveLearningMetric.DIAGNOSTIC_TRIGGER_PRECISION] == 1


def test_weight_calibration_is_conservative_and_requires_manual_approval():
    samples = [
        WeightCalibrationSample(
            sample_id=f"s-{index}",
            assessment_source=AssessmentSource.GENERATED_QUESTION,
            evidence_outcome=EvidenceOutcome.CORRECT,
            reference_outcome=EvidenceOutcome.PARTIAL,
            current_strength=0.5,
            reference_score=0.4,
        )
        for index in range(5)
    ]
    report = calibrate_weight_caps(samples)
    generated = next(
        item
        for item in report.source_reports
        if item.assessment_source is AssessmentSource.GENERATED_QUESTION
    )

    assert report.eligible_count == 5
    assert report.mean_absolute_error == 0.1
    assert generated.recommended_cap == 0.4
    assert generated.current_cap == 0.5
    assert generated.recommendation_status == "candidate_requires_approval"
    assert report.manual_approval_required is True
