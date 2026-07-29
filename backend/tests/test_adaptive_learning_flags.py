from types import SimpleNamespace

from app.modules.agent.adaptive_learning_flags import (
    AdaptiveLearningFeatureFlags,
    AdaptiveLearningFlag,
    FeatureFlagMode,
)


def _settings(**overrides):
    values = {
        "ADAPTIVE_LEARNING_CONVERSATION_DECISION_V2": "active",
        "ADAPTIVE_LEARNING_LEARNING_OBSERVER_V1": "shadow",
        "ADAPTIVE_LEARNING_OPEN_ANSWER_ASSESSOR_V1": "active",
        "ADAPTIVE_LEARNING_MASTERY_MODEL_V2": "active",
        "ADAPTIVE_LEARNING_CANARY_PERCENT": 10,
        "ADAPTIVE_LEARNING_FLAG_OVERRIDES": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_active_and_shadow_modes_are_versioned_and_stable():
    flags = AdaptiveLearningFeatureFlags(_settings())

    first = flags.decision(
        AdaptiveLearningFlag.CONVERSATION_DECISION_V2,
        subject_id="user-1",
    )
    second = flags.decision(
        AdaptiveLearningFlag.CONVERSATION_DECISION_V2,
        subject_id="user-1",
    )
    observer = flags.decision(
        AdaptiveLearningFlag.LEARNING_OBSERVER_V1,
        subject_id="user-1",
    )

    assert first == second
    assert first.enabled is True
    assert first.is_authoritative is True
    assert observer.mode is FeatureFlagMode.SHADOW
    assert observer.enabled is True
    assert observer.is_authoritative is False
    assert observer.policy_version == "adaptive-learning-flags-v1"


def test_canary_uses_stable_bucket_and_override_percent():
    flags = AdaptiveLearningFeatureFlags(
        _settings(
            ADAPTIVE_LEARNING_CONVERSATION_DECISION_V2="disabled",
            ADAPTIVE_LEARNING_FLAG_OVERRIDES="conversation_decision_v2=canary:100",
        )
    )

    decision = flags.decision(
        AdaptiveLearningFlag.CONVERSATION_DECISION_V2,
        subject_id="user-2",
    )

    assert decision.mode is FeatureFlagMode.CANARY
    assert decision.rollout_percent == 100
    assert decision.enabled is True
    assert decision.treatment == "canary"


def test_invalid_mode_fails_closed_and_snapshot_contains_all_flags():
    flags = AdaptiveLearningFeatureFlags(
        _settings(ADAPTIVE_LEARNING_MASTERY_MODEL_V2="typo")
    )

    decision = flags.decision(
        AdaptiveLearningFlag.MASTERY_MODEL_V2,
        subject_id="user-3",
    )
    snapshot = flags.snapshot(subject_id="user-3")

    assert decision.mode is FeatureFlagMode.DISABLED
    assert decision.enabled is False
    assert decision.is_authoritative is False
    assert set(snapshot["flags"]) == {
        "conversation_decision_v2",
        "learning_observer_v1",
        "open_answer_assessor_v1",
        "mastery_model_v2",
    }
