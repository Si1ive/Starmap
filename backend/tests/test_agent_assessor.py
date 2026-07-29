import pytest
from pydantic import ValidationError

from app.modules.agent.model_runtime.assessor import (
    CriterionScore,
    OpenAnswerAssessment,
    OpenAnswerAssessorDeps,
    OpenAnswerRubric,
    normalize_open_answer_assessment,
    weighted_criterion_score,
)


def _rubric() -> OpenAnswerRubric:
    return OpenAnswerRubric(
        version="rubric-v1",
        source_answer_source="manual",
        criteria=[
            {
                "criterion_id": "core_concepts",
                "description": "覆盖核心概念",
                "weight": 0.7,
            },
            {
                "criterion_id": "reasoning",
                "description": "说明推理过程",
                "weight": 0.3,
            },
        ],
    )


def _deps() -> OpenAnswerAssessorDeps:
    return OpenAnswerAssessorDeps(
        run_id="run_assessor_001",
        user_id="user_assessor_001",
        question_id="question_assessor_001",
    )


def test_assessor_server_owns_evidence_id_and_partial_score():
    rubric = _rubric()
    assessment = OpenAnswerAssessment(
        verdict="partial",
        criterion_scores=[
            CriterionScore(criterion_id="core_concepts", score=0.8),
            CriterionScore(criterion_id="reasoning", score=0.4),
        ],
        assessment_confidence=0.9,
        evidence_id="model-chosen-id",
    )

    normalized = normalize_open_answer_assessment(
        assessment,
        deps=_deps(),
        rubric=rubric,
    )

    assert normalized.verdict == "partial"
    assert normalized.evidence_id == ("open:run_assessor_001:question_assessor_001")
    assert weighted_criterion_score(rubric, normalized) == 0.68


def test_assessor_low_confidence_becomes_ungradable_without_scores():
    assessment = OpenAnswerAssessment(
        verdict="correct",
        criterion_scores=[
            CriterionScore(criterion_id="core_concepts", score=1.0),
            CriterionScore(criterion_id="reasoning", score=1.0),
        ],
        assessment_confidence=0.59,
    )

    normalized = normalize_open_answer_assessment(
        assessment,
        deps=_deps(),
        rubric=_rubric(),
    )

    assert normalized.verdict == "ungradable"
    assert normalized.criterion_scores == []
    assert normalized.feedback_reason == "评分置信度不足，需要更明确回答"


def test_assessor_output_forbids_mastery_fields():
    with pytest.raises(ValidationError):
        OpenAnswerAssessment.model_validate(
            {
                "verdict": "correct",
                "criterion_scores": [],
                "assessment_confidence": 0.9,
                "mastery_delta": 1.0,
            }
        )
