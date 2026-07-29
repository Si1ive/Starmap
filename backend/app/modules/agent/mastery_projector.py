"""把可信学习证据投影为可解释的知识点掌握度状态。"""

from __future__ import annotations

import math
from datetime import datetime

from app.modules.learning.contracts import EvidenceOutcome, LearningEvidence
from app.modules.learning.evidence import EvidenceWeightPolicy

from .models import UserLearningMastery
from .time_utils import utc_now

MASTERY_STATE_MODEL_VERSION = "mastery-beta-v1"


class MasteryProjector:
    """使用加权 alpha/beta 证据参数累计知识点掌握度。

    alpha/beta 是无先验的加权伪计数，因此第一条正确证据仍保持旧读取字段的
    ``mastery_score=1.0``，第一条错误证据仍为 ``0.0``；``uncertainty`` 单独反映
    证据质量和数量，随 evidence mass 增加而下降。多知识点题目必须显式指定目标
    知识点，服务端只会使用该证据在 coverage 中对应的分摊权重。
    """

    def __init__(
        self,
        *,
        weight_policy: EvidenceWeightPolicy | None = None,
        state_model_version: str = MASTERY_STATE_MODEL_VERSION,
    ) -> None:
        self.weight_policy = weight_policy or EvidenceWeightPolicy()
        self.state_model_version = state_model_version

    def apply(
        self,
        mastery: UserLearningMastery | None,
        evidence: LearningEvidence,
        *,
        knowledge_point_id: str | None = None,
        user_id: str | None = None,
        subject_id: str | None = None,
        evidence_at: datetime | None = None,
        partial_credit: object | None = None,
        suggested_weight: object | None = None,
    ) -> UserLearningMastery | None:
        """将一条证据应用到一个知识点行并返回该行。

        exposure、observation、自我声明、unknown 和 ungradable 只返回原行，不
        增加任何掌握度参数。``mastery is None`` 时要求调用方提供 user/KP，便于
        在数据库投影函数中安全创建新行。
        """
        if not evidence.is_mastery_evidence:
            return mastery

        target_id = (knowledge_point_id or "").strip()
        if not target_id:
            if len(evidence.knowledge_point_coverage) != 1:
                raise ValueError("多知识点证据投影时必须指定 knowledge_point_id")
            target_id = next(iter(evidence.knowledge_point_coverage))
        if target_id not in evidence.knowledge_point_coverage:
            raise ValueError("掌握度投影目标不在证据 coverage 中")

        if mastery is None:
            if not user_id:
                raise ValueError("创建掌握度记录需要 user_id")
            mastery = UserLearningMastery(
                user_id=user_id,
                subject_id=subject_id,
                knowledge_point_id=target_id,
                mastery_score=0.0,
                evidence_count=0,
                correct_count=0,
                incorrect_count=0,
                mastery_alpha=0.0,
                mastery_beta=0.0,
                evidence_mass=0.0,
                uncertainty=1.0,
                state_model_version=self.state_model_version,
            )

        alpha, beta, mass = self._existing_parameters(mastery)
        weight = self.weight_policy.calculate(
            evidence,
            suggested_weight=suggested_weight,
        ).point_strength.get(target_id, 0.0)
        if weight <= 0.0:
            return mastery

        if evidence.evidence_outcome is EvidenceOutcome.CORRECT:
            positive_mass, negative_mass = weight, 0.0
        elif evidence.evidence_outcome is EvidenceOutcome.INCORRECT:
            positive_mass, negative_mass = 0.0, weight
        elif evidence.evidence_outcome is EvidenceOutcome.PARTIAL:
            credit = _partial_credit(partial_credit)
            positive_mass = weight * credit
            negative_mass = weight * (1.0 - credit)
        else:
            return mastery

        alpha += positive_mass
        beta += negative_mass
        mass += weight
        total = alpha + beta
        score = alpha / total if total > 0 else 0.0

        mastery.mastery_alpha = round(alpha, 6)
        mastery.mastery_beta = round(beta, 6)
        mastery.evidence_mass = round(mass, 6)
        mastery.mastery_score = round(max(0.0, min(1.0, score)), 4)
        mastery.evidence_count = int(getattr(mastery, "evidence_count", 0) or 0) + 1
        if evidence.evidence_outcome is EvidenceOutcome.CORRECT:
            mastery.correct_count = int(getattr(mastery, "correct_count", 0) or 0) + 1
        elif evidence.evidence_outcome is EvidenceOutcome.INCORRECT:
            mastery.incorrect_count = (
                int(getattr(mastery, "incorrect_count", 0) or 0) + 1
            )
        else:
            metadata = dict(mastery.metadata_json or {})
            metadata["partial_count"] = int(metadata.get("partial_count") or 0) + 1
            mastery.metadata_json = metadata

        occurred_at = evidence_at or utc_now()
        mastery.last_evidence_id = evidence.evidence_id
        mastery.last_evidence_at = occurred_at
        # 旧 selector 仍从 last_graded_at 读取；保留同一证据时间以维持衰减语义。
        mastery.last_graded_at = occurred_at
        mastery.uncertainty = round(1.0 / math.sqrt(1.0 + max(mass, 0.0)), 6)
        mastery.state_model_version = self.state_model_version
        metadata = dict(mastery.metadata_json or {})
        metadata.update(
            {
                "state_model_version": self.state_model_version,
                "evidence_mass": mastery.evidence_mass,
            }
        )
        mastery.metadata_json = metadata
        return mastery

    @staticmethod
    def _existing_parameters(
        mastery: UserLearningMastery,
    ) -> tuple[float, float, float]:
        evidence_count = float(getattr(mastery, "evidence_count", 0) or 0)
        score = _bounded(getattr(mastery, "mastery_score", 0.0))
        alpha = _optional_nonnegative(getattr(mastery, "mastery_alpha", None))
        beta = _optional_nonnegative(getattr(mastery, "mastery_beta", None))
        mass = _optional_nonnegative(getattr(mastery, "evidence_mass", None))
        if alpha is None or beta is None:
            alpha = score * evidence_count
            beta = (1.0 - score) * evidence_count
        if mass is None:
            mass = evidence_count
        return alpha, beta, mass


def _partial_credit(value: object | None) -> float:
    if value is None or isinstance(value, bool):
        return 0.5
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(parsed):
        return 0.5
    return max(0.0, min(1.0, parsed))


def _optional_nonnegative(value: object | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _bounded(value: object | None) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return max(0.0, min(1.0, parsed))


__all__ = ["MASTERY_STATE_MODEL_VERSION", "MasteryProjector"]
