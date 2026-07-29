from evals.adaptive_learning import (
    ADAPTIVE_LEARNING_EVALS_VERSION,
    FIXED_EVALUATION_DATASET_NAME,
    build_adaptive_learning_evaluation_dataset,
    fixed_adaptive_learning_cases,
    run_fixed_adaptive_learning_evals_sync,
)


def test_fixed_adaptive_learning_dataset_covers_required_scenarios():
    cases = fixed_adaptive_learning_cases()

    assert len(cases) == 10
    assert {case.name for case in cases} == {
        "only_ask_topic",
        "explanation_without_answer",
        "objective_answer_wrong",
        "objective_answer_right",
        "hint_assisted_right",
        "transfer_weakness",
        "open_answer_low_confidence",
        "multi_knowledge_point",
        "observer_assessor_retry",
        "rag_tool_policy_rejected",
    }


def test_fixed_adaptive_learning_evals_are_deterministic_and_side_effect_free():
    report = run_fixed_adaptive_learning_evals_sync()
    averages = report.averages()

    assert report.name == ADAPTIVE_LEARNING_EVALS_VERSION
    assert len(report.cases) == 10
    assert averages is not None
    assert averages.scores["fixed_output_matches_expected"] == 1.0
    assert averages.scores["tool_policy_gate_safety"] == 1.0
    assert averages.scores["replay_key_preserved"] == 1.0
    assert averages.scores["topic_resolution_accuracy"] == 1.0
    assert averages.scores["observation_classification_precision"] == 1.0
    assert averages.scores["assessment_agreement"] == 1.0
    assert averages.scores["next_question_prediction"] == 1.0
    assert averages.scores["tool_policy_violation_count"] == 0.0


def test_dataset_has_versioned_metrics_evaluator():
    dataset = build_adaptive_learning_evaluation_dataset()

    assert dataset.name == FIXED_EVALUATION_DATASET_NAME
    assert len(dataset.evaluators) == 1
    assert (
        dataset.evaluators[0].get_evaluator_version() == ADAPTIVE_LEARNING_EVALS_VERSION
    )
