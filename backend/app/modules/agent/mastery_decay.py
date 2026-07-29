"""UserLearningMastery 的确定性读时衰减策略。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .time_utils import as_utc, utc_now
from .mastery_projector import MASTERY_STATE_MODEL_VERSION

MASTERY_DECAY_POLICY_VERSION = "mastery-decay-v1"
MASTERY_DECAY_HALF_LIFE_DAYS = 90.0
MASTERY_DECAY_RETENTION_FLOOR = 0.2


@dataclass(frozen=True, slots=True)
class EffectiveMastery:
    """保留原始分数并描述某个 UTC 时点的派生有效掌握度。"""

    raw_score: float
    effective_score: float
    evidence_at: datetime
    age_days: float
    policy_version: str = MASTERY_DECAY_POLICY_VERSION
    state_model_version: str = MASTERY_STATE_MODEL_VERSION


def calculate_effective_mastery(
    raw_score: float,
    *,
    evidence_at: datetime,
    now: datetime | None = None,
    state_model_version: str = MASTERY_STATE_MODEL_VERSION,
) -> EffectiveMastery:
    """按 90 天半衰期向保留地板衰减，不修改原始累计分数。

    数据库中的 naive DATETIME 按 UTC 解释；未来证据的年龄钳制为 0，避免时钟偏差
    产生超过原始分数的结果。保留地板永远不高于原分数，因此低分不会因策略被抬高。
    """
    normalized_raw = min(1.0, max(0.0, float(raw_score)))
    normalized_evidence_at = as_utc(evidence_at)
    normalized_now = as_utc(now or utc_now())
    if normalized_evidence_at is None or normalized_now is None:
        raise ValueError("掌握度衰减需要有效的证据时间和当前时间")

    age_seconds = max(
        0.0,
        (normalized_now - normalized_evidence_at).total_seconds(),
    )
    age_days = age_seconds / 86_400
    retention_floor = min(normalized_raw, MASTERY_DECAY_RETENTION_FLOOR)
    retention_factor = 0.5 ** (age_days / MASTERY_DECAY_HALF_LIFE_DAYS)
    effective_score = (
        retention_floor + (normalized_raw - retention_floor) * retention_factor
    )
    return EffectiveMastery(
        raw_score=round(normalized_raw, 4),
        effective_score=round(effective_score, 4),
        evidence_at=normalized_evidence_at,
        age_days=round(age_days, 4),
        state_model_version=state_model_version,
    )
