"""自适应学习证据契约和旧活动事件兼容边界测试。"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.learning.contracts import (
    AnswerSource,
    AssessmentSource,
    ErrorTag,
    EvidenceContext,
    EvidenceOutcome,
    EvidenceType,
    LearningEvidence,
    learning_evidence_from_activity_event,
)
from app.modules.learning.models import LearningActivityEvent


def _evidence(**overrides):
    payload = {
        "source_id": "run-1",
        "evidence_type": EvidenceType.OBJECTIVE_ASSESSMENT,
        "evidence_outcome": EvidenceOutcome.CORRECT,
        "assessment_source": AssessmentSource.DETERMINISTIC,
        "confidence": 0.9,
        "evidence_strength": 1.0,
        "knowledge_point_ids": ["kp-1"],
        "context": {
            "question_id": "question-1",
            "answer_source": AnswerSource.QUESTION_BANK,
            "hint_levels_used": [],
            "answer_exposed": False,
        },
    }
    payload.update(overrides)
    return LearningEvidence.model_validate(payload)


def test_contract_enums_are_closed_and_confidence_is_bounded():
    assert {item.value for item in EvidenceType} == {
        "exposure",
        "self_report",
        "open_response",
        "objective_assessment",
        "hint_assisted",
        "transfer",
        "observation",
    }
    assert {item.value for item in EvidenceOutcome} == {
        "unknown",
        "correct",
        "partial",
        "incorrect",
        "ungradable",
    }
    assert {item.value for item in AssessmentSource} == {
        "deterministic",
        "llm_rubric",
        "user_report",
        "question_bank",
        "generated_question",
    }
    assert {item.value for item in ErrorTag} == {
        "concept_gap",
        "misconception",
        "retrieval_gap",
        "procedure_gap",
        "transfer_gap",
        "careless_error",
    }

    with pytest.raises(ValidationError):
        _evidence(evidence_type="future_evidence")
    with pytest.raises(ValidationError):
        _evidence(confidence=1.01)
    with pytest.raises(ValidationError):
        _evidence(confidence=-0.01)
    with pytest.raises(ValidationError):
        _evidence(source_id="")


def test_model_cannot_add_arbitrary_mastery_or_weight_fields():
    with pytest.raises(ValidationError, match="mastery_score"):
        _evidence(mastery_score=0.99)
    with pytest.raises(ValidationError, match="suggested_weight"):
        _evidence(suggested_weight=1.0)


def test_multi_knowledge_point_evidence_requires_normalized_coverage():
    evidence = _evidence(
        knowledge_point_ids=["kp-1", "kp-2"],
        knowledge_point_coverage={"kp-1": 0.25, "kp-2": 0.75},
    )
    assert evidence.knowledge_point_coverage == {"kp-1": 0.25, "kp-2": 0.75}
    assert evidence.is_mastery_evidence is True

    with pytest.raises(ValidationError, match="coverage"):
        _evidence(
            knowledge_point_ids=["kp-1", "kp-2"],
            knowledge_point_coverage={},
        )
    with pytest.raises(ValidationError, match="总和"):
        _evidence(
            knowledge_point_ids=["kp-1", "kp-2"],
            knowledge_point_coverage={"kp-1": 0.5, "kp-2": 0.4},
        )
    with pytest.raises(ValidationError, match="重复"):
        _evidence(knowledge_point_ids=["kp-1", "kp-1"])


def test_exposure_and_self_report_cannot_become_strong_mastery_evidence():
    exposure = LearningEvidence(
        source_id="artifact-explain-1",
        evidence_type=EvidenceType.EXPOSURE,
        evidence_outcome=EvidenceOutcome.UNKNOWN,
        evidence_strength=0.0,
        context=EvidenceContext(),
    )
    assert exposure.is_mastery_evidence is False
    assert exposure.evidence_id == "artifact-explain-1"

    with pytest.raises(ValidationError, match="不能携带"):
        LearningEvidence(
            source_id="message-1",
            evidence_type=EvidenceType.EXPOSURE,
            evidence_outcome=EvidenceOutcome.CORRECT,
            evidence_strength=1.0,
        )
    with pytest.raises(ValidationError, match="自我声明"):
        LearningEvidence(
            source_id="message-2",
            evidence_type=EvidenceType.SELF_REPORT,
            evidence_outcome=EvidenceOutcome.CORRECT,
            assessment_source=AssessmentSource.USER_REPORT,
            evidence_strength=0.25,
        )
    with pytest.raises(ValidationError, match="强评分"):
        LearningEvidence(
            source_id="message-3",
            evidence_type=EvidenceType.SELF_REPORT,
            evidence_outcome=EvidenceOutcome.UNKNOWN,
            assessment_source=AssessmentSource.USER_REPORT,
            evidence_strength=0.26,
        )


def test_hint_assisted_evidence_requires_hint_context():
    with pytest.raises(ValidationError, match="提示级别"):
        _evidence(
            evidence_type=EvidenceType.HINT_ASSISTED,
            context={
                "question_id": "question-1",
                "answer_source": AnswerSource.QUESTION_BANK,
                "answer_exposed": False,
                "hint_levels_used": [],
            },
        )

    evidence = _evidence(
        evidence_type=EvidenceType.HINT_ASSISTED,
        context={
            "question_id": "question-1",
            "answer_source": AnswerSource.QUESTION_BANK,
            "answer_exposed": False,
            "hint_levels_used": ["concept"],
        },
    )
    assert evidence.context.hint_levels_used == ["concept"]


def test_legacy_explanation_defaults_to_zero_strength_exposure():
    event = SimpleNamespace(
        event_type="agent_explanation_completed",
        source_type="agent_discussion",
        source_id="artifact-explain-1",
        is_correct=None,
        knowledge_point_ids_json=["kp-1"],
        payload_json={"title": "二分查找", "quality": 0.35},
    )

    evidence = learning_evidence_from_activity_event(event)

    assert evidence.evidence_type is EvidenceType.EXPOSURE
    assert evidence.evidence_outcome is EvidenceOutcome.UNKNOWN
    assert evidence.evidence_strength == 0.0
    assert evidence.is_mastery_evidence is False
    assert evidence.context.answer_source is AnswerSource.NOT_APPLICABLE


def test_activity_model_exposes_the_same_read_only_compatibility_adapter():
    event = LearningActivityEvent(
        event_type="agent_explanation_completed",
        source_type="agent_discussion",
        source_id="artifact-explain-2",
        topic_keywords_json=["二分查找"],
        quality=0.35,
        is_correct=None,
        knowledge_point_ids_json=["kp-1"],
        payload_json={"title": "二分查找"},
    )

    evidence = event.to_learning_evidence()

    assert evidence.evidence_type is EvidenceType.EXPOSURE
    assert evidence.evidence_strength == 0.0


def test_legacy_assessment_defaults_keep_verdict_and_idempotency_identity():
    event = SimpleNamespace(
        event_type="practice_answer_graded",
        source_type="agent_practice",
        source_id="session-1:item-1",
        is_correct=True,
        knowledge_point_ids_json=["kp-1", "kp-2"],
        payload_json={
            "question_id": "question-1",
            "hint_levels_used": ["concept"],
            "answer_source": "llm",
        },
    )

    evidence = LearningEvidence.from_legacy_activity_event(event)

    assert evidence.evidence_type is EvidenceType.HINT_ASSISTED
    assert evidence.evidence_outcome is EvidenceOutcome.CORRECT
    assert evidence.assessment_source is AssessmentSource.DETERMINISTIC
    assert evidence.context.answer_source is AnswerSource.LLM
    assert evidence.context.hint_levels_used == ["concept"]
    assert evidence.knowledge_point_coverage == {"kp-1": 0.5, "kp-2": 0.5}
    assert (
        evidence.idempotency_key == "agent_practice:session-1:item-1:session-1:item-1"
    )
    assert evidence.is_mastery_evidence is True


def test_legacy_event_without_source_id_fails_at_contract_boundary():
    with pytest.raises(ValidationError, match="source_id"):
        learning_evidence_from_activity_event(
            {"event_type": "agent_explanation_completed"}
        )
