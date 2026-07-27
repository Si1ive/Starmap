"""学习掌握度读时衰减的纯函数边界。"""

from datetime import UTC, datetime, timedelta

from app.modules.agent.mastery_decay import (
    MASTERY_DECAY_POLICY_VERSION,
    calculate_effective_mastery,
)


def test_recent_evidence_keeps_raw_mastery_score():
    now = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)

    result = calculate_effective_mastery(0.85, evidence_at=now, now=now)

    assert result.raw_score == 0.85
    assert result.effective_score == 0.85
    assert result.age_days == 0
    assert result.policy_version == MASTERY_DECAY_POLICY_VERSION


def test_stale_mastery_decays_by_half_life_toward_retention_floor():
    now = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)

    result = calculate_effective_mastery(
        1.0,
        evidence_at=now - timedelta(days=180),
        now=now,
    )

    assert result.effective_score == 0.4
    assert result.age_days == 180


def test_retention_floor_never_raises_an_already_low_score():
    now = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)

    result = calculate_effective_mastery(
        0.1,
        evidence_at=now - timedelta(days=365),
        now=now,
    )

    assert result.effective_score == 0.1


def test_future_and_naive_utc_evidence_are_handled_deterministically():
    aware_now = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)
    naive_now = aware_now.replace(tzinfo=None)

    future = calculate_effective_mastery(
        0.9,
        evidence_at=naive_now + timedelta(days=1),
        now=aware_now,
    )
    naive = calculate_effective_mastery(
        1.0,
        evidence_at=naive_now - timedelta(days=90),
        now=naive_now,
    )

    assert future.effective_score == 0.9
    assert future.age_days == 0
    assert naive.effective_score == 0.6
    assert naive.evidence_at.tzinfo == UTC
