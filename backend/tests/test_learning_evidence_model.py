"""阶段三学习证据门禁、权重和掌握度 projector 的领域回归。"""

import pytest
from pydantic import ValidationError

from app.modules.agent.mastery_projector import MasteryProjector
from app.modules.learning.contracts import (
    AnswerSource,
    AssessmentSource,
    LearningEvidence,
)
from app.modules.learning.evidence import (
    EvidenceGate,
    EvidenceGateError,
    EvidenceWeightPolicy,
    build_assessment_evidence,
)


def _evidence(**overrides):
    payload = {
        "source_id": "evidence-1",
        "source_type": "agent_grade",
        "verdict": "correct",
        "question_id": "question-1",
        "knowledge_point_ids": ["kp-1"],
        "answer_source": AnswerSource.MANUAL,
        "assessment_source": AssessmentSource.DETERMINISTIC,
    }
    payload.update(overrides)
    return build_assessment_evidence(**payload)


def test_evidence_gate_rejects_cross_user_run_and_unverified_knowledge_point():
    evidence = _evidence()
    gate = EvidenceGate()

    with pytest.raises(EvidenceGateError, match="来源用户"):
        gate.validate(
            evidence,
            owner_user_id="user-1",
            source_user_id="user-2",
            source_run_id="run-1",
            expected_question_id="question-1",
            verified_knowledge_point_ids=["kp-1"],
        )

    with pytest.raises(EvidenceGateError, match="未验证"):
        gate.validate(
            _evidence(knowledge_point_ids=["kp-2"]),
            owner_user_id="user-1",
            source_user_id="user-1",
            source_run_id="run-1",
            expected_question_id="question-1",
            verified_knowledge_point_ids=["kp-1"],
        )


def test_evidence_gate_does_not_allow_unknown_answer_source_to_update_mastery():
    evidence = _evidence(answer_source=AnswerSource.UNKNOWN)

    with pytest.raises(EvidenceGateError, match="标准答案来源"):
        EvidenceGate().validate(
            evidence,
            owner_user_id="user-1",
            source_user_id="user-1",
            source_run_id="run-1",
            expected_question_id="question-1",
            verified_knowledge_point_ids=["kp-1"],
        )


def test_unmapped_practice_fact_can_be_recorded_without_mastery_projection():
    evidence = _evidence(source_type="question", knowledge_point_ids=[])

    validated = EvidenceGate().validate(
        evidence,
        owner_user_id="user-1",
        source_user_id="user-1",
        expected_question_id="question-1",
        require_knowledge_point_coverage=False,
    )

    assert validated.knowledge_point_coverage == {}
    assert EvidenceWeightPolicy().calculate(validated).evidence_strength == 0.0


def test_weight_policy_reduces_hint_generated_and_exposed_evidence():
    policy = EvidenceWeightPolicy()
    independent = policy.calculate(_evidence())
    hinted = policy.calculate(
        _evidence(evidence_type="hint_assisted", hint_levels_used=["concept"])
    )
    generated = policy.calculate(
        _evidence(
            answer_source=AnswerSource.GENERATED_QUESTION,
            assessment_source=AssessmentSource.GENERATED_QUESTION,
        )
    )
    exposed = policy.calculate(_evidence(answer_exposed=True))

    assert independent.evidence_strength == 1.0
    assert hinted.evidence_strength < independent.evidence_strength
    assert generated.evidence_strength < independent.evidence_strength
    assert exposed.evidence_strength < generated.evidence_strength
    assert "hint_assisted" in hinted.reasons
    assert "answer_exposed" in exposed.reasons


def test_question_bank_answer_source_infers_question_bank_assessment_source():
    evidence = _evidence(
        answer_source=AnswerSource.QUESTION_BANK, assessment_source=None
    )

    assert evidence.assessment_source is AssessmentSource.QUESTION_BANK


def test_suggested_weight_is_only_a_lower_capped_request():
    policy = EvidenceWeightPolicy()
    evidence = _evidence()

    assert policy.calculate(evidence, suggested_weight=2).evidence_strength == 1.0
    assert policy.calculate(evidence, suggested_weight=0.2).evidence_strength == 0.2
    assert (
        policy.calculate(evidence, suggested_weight="not-a-number").evidence_strength
        == 1.0
    )


def test_mastery_projector_accumulates_weighted_beta_and_preserves_legacy_score():
    projector = MasteryProjector()
    mastery = projector.apply(
        None,
        _evidence(source_id="correct-1"),
        user_id="user-1",
        evidence_at=None,
    )
    assert mastery is not None
    assert mastery.mastery_alpha == 1.0
    assert mastery.mastery_beta == 0.0
    assert mastery.evidence_mass == 1.0
    assert mastery.mastery_score == 1.0
    assert mastery.evidence_count == 1
    assert mastery.uncertainty < 1.0

    projector.apply(
        mastery,
        _evidence(source_id="incorrect-1", verdict="incorrect"),
        knowledge_point_id="kp-1",
        partial_credit=None,
    )
    assert mastery.mastery_alpha == 1.0
    assert mastery.mastery_beta == 1.0
    assert mastery.evidence_mass == 2.0
    assert mastery.mastery_score == 0.5
    assert mastery.correct_count == 1
    assert mastery.incorrect_count == 1


def test_mastery_projector_splits_partial_and_multi_point_coverage():
    projector = MasteryProjector()
    evidence = _evidence(
        source_id="partial-multi",
        verdict="partial",
        knowledge_point_ids=["kp-1", "kp-2"],
        knowledge_point_coverage={"kp-1": 0.25, "kp-2": 0.75},
    )
    first = projector.apply(
        None,
        evidence,
        knowledge_point_id="kp-1",
        user_id="user-1",
        partial_credit=0.25,
    )
    second = projector.apply(
        None,
        evidence,
        knowledge_point_id="kp-2",
        user_id="user-1",
        partial_credit=0.25,
    )

    assert first is not None and second is not None
    assert first.mastery_alpha == 0.0625
    assert first.mastery_beta == 0.1875
    assert first.evidence_mass == 0.25
    assert second.mastery_alpha == 0.1875
    assert second.mastery_beta == 0.5625
    assert second.evidence_mass == 0.75


def test_mastery_projector_rejects_ambiguous_multi_point_target():
    with pytest.raises(ValueError, match="必须指定 knowledge_point_id"):
        MasteryProjector().apply(
            None,
            _evidence(
                knowledge_point_ids=["kp-1", "kp-2"],
                knowledge_point_coverage={"kp-1": 0.5, "kp-2": 0.5},
            ),
            user_id="user-1",
        )


def test_evidence_contract_still_rejects_model_mastery_write_fields():
    with pytest.raises(ValidationError, match="mastery_score"):
        LearningEvidence.model_validate(
            {
                "source_id": "evidence-1",
                "evidence_type": "objective_assessment",
                "evidence_outcome": "correct",
                "assessment_source": "deterministic",
                "knowledge_point_ids": ["kp-1"],
                "mastery_score": 0.9,
            }
        )
