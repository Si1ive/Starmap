"""自适应学习 Agent 的版本化灰度开关。

阶段七的开关只决定某个版本是否可以参与本轮执行，不向模型暴露任何权限，也
不替代 EvidenceGate、ToolRegistry 或掌握度投影的领域校验。canary 使用用户
稳定哈希分桶，确保同一用户在一次灰度期间不会随机切换处理路径。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings

ADAPTIVE_LEARNING_FLAG_POLICY_VERSION = "adaptive-learning-flags-v1"


class AdaptiveLearningFlag(str, Enum):
    """阶段七允许独立回退的四个版本开关。"""

    CONVERSATION_DECISION_V2 = "conversation_decision_v2"
    LEARNING_OBSERVER_V1 = "learning_observer_v1"
    OPEN_ANSWER_ASSESSOR_V1 = "open_answer_assessor_v1"
    MASTERY_MODEL_V2 = "mastery_model_v2"


class FeatureFlagMode(str, Enum):
    """开关的发布状态。"""

    DISABLED = "disabled"
    SHADOW = "shadow"
    CANARY = "canary"
    ACTIVE = "active"


class FeatureFlagDecision(BaseModel):
    """写入 Run 审计和评估样本的不可变开关决策。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    flag: AdaptiveLearningFlag
    mode: FeatureFlagMode
    enabled: bool
    authoritative: bool
    treatment: str = Field(min_length=1, max_length=16)
    rollout_percent: int = Field(ge=0, le=100)
    bucket: int = Field(ge=0, le=99)
    policy_version: str = ADAPTIVE_LEARNING_FLAG_POLICY_VERSION

    @property
    def is_shadow(self) -> bool:
        """是否执行但不允许其结果成为用户/掌握度权威结果。"""

        return self.enabled and self.mode is FeatureFlagMode.SHADOW

    @property
    def is_authoritative(self) -> bool:
        """是否允许该版本的输出进入原有业务副作用边界。"""

        return self.enabled and self.authoritative


@dataclass(frozen=True)
class _FlagSetting:
    setting_name: str
    default_mode: FeatureFlagMode


_FLAG_SETTINGS: dict[AdaptiveLearningFlag, _FlagSetting] = {
    AdaptiveLearningFlag.CONVERSATION_DECISION_V2: _FlagSetting(
        "ADAPTIVE_LEARNING_CONVERSATION_DECISION_V2", FeatureFlagMode.ACTIVE
    ),
    AdaptiveLearningFlag.LEARNING_OBSERVER_V1: _FlagSetting(
        "ADAPTIVE_LEARNING_LEARNING_OBSERVER_V1", FeatureFlagMode.SHADOW
    ),
    AdaptiveLearningFlag.OPEN_ANSWER_ASSESSOR_V1: _FlagSetting(
        "ADAPTIVE_LEARNING_OPEN_ANSWER_ASSESSOR_V1", FeatureFlagMode.ACTIVE
    ),
    AdaptiveLearningFlag.MASTERY_MODEL_V2: _FlagSetting(
        "ADAPTIVE_LEARNING_MASTERY_MODEL_V2", FeatureFlagMode.ACTIVE
    ),
}


def _stable_bucket(flag: AdaptiveLearningFlag, subject_id: object) -> int:
    subject = str(subject_id or "").strip() or "anonymous"
    digest = hashlib.sha256(f"{flag.value}:{subject}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 100


def _parse_percent(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(100, parsed))


def _parse_mode(value: object, default: FeatureFlagMode) -> FeatureFlagMode:
    try:
        return FeatureFlagMode(str(value or "").strip().lower())
    except ValueError:
        # 配置错误必须 fail closed，不能因为拼写错误意外全量打开新版本。
        return FeatureFlagMode.DISABLED


class AdaptiveLearningFeatureFlags:
    """从 Settings 解析开关，并生成稳定的本轮处理决策。"""

    def __init__(self, settings_object: Any = None):
        self._settings = settings_object or settings

    def _override_values(
        self,
    ) -> dict[AdaptiveLearningFlag, tuple[FeatureFlagMode, int | None]]:
        """读取 ``flag=mode[:percent]`` 形式的部署覆盖。"""

        raw = str(getattr(self._settings, "ADAPTIVE_LEARNING_FLAG_OVERRIDES", "") or "")
        result: dict[AdaptiveLearningFlag, tuple[FeatureFlagMode, int | None]] = {}
        for item in raw.split(","):
            item = item.strip()
            if not item or "=" not in item:
                continue
            raw_flag, raw_value = (part.strip() for part in item.split("=", 1))
            try:
                flag = AdaptiveLearningFlag(raw_flag)
            except ValueError:
                continue
            mode_text, separator, percent_text = raw_value.partition(":")
            mode = _parse_mode(mode_text, FeatureFlagMode.DISABLED)
            percent = _parse_percent(percent_text, 100) if separator else None
            result[flag] = (mode, percent)
        return result

    def _configured(self, flag: AdaptiveLearningFlag) -> tuple[FeatureFlagMode, int]:
        definition = _FLAG_SETTINGS[flag]
        raw_mode = getattr(
            self._settings,
            definition.setting_name,
            definition.default_mode.value,
        )
        mode = _parse_mode(raw_mode, definition.default_mode)
        default_percent = _parse_percent(
            getattr(self._settings, "ADAPTIVE_LEARNING_CANARY_PERCENT", 10),
            10,
        )
        rollout_percent = (
            100
            if mode
            in {
                FeatureFlagMode.ACTIVE,
                FeatureFlagMode.SHADOW,
            }
            else default_percent
        )
        override = self._override_values().get(flag)
        if override is not None:
            mode, override_percent = override
            rollout_percent = (
                _parse_percent(override_percent, default_percent)
                if override_percent is not None
                else (
                    100
                    if mode in {FeatureFlagMode.ACTIVE, FeatureFlagMode.SHADOW}
                    else default_percent
                )
            )
        return mode, rollout_percent

    def decision(
        self, flag: AdaptiveLearningFlag | str, *, subject_id: object
    ) -> FeatureFlagDecision:
        """返回指定用户在本轮的稳定处理结果。"""

        normalized_flag = (
            flag
            if isinstance(flag, AdaptiveLearningFlag)
            else AdaptiveLearningFlag(str(flag))
        )
        mode, rollout_percent = self._configured(normalized_flag)
        bucket = _stable_bucket(normalized_flag, subject_id)
        enabled = mode is not FeatureFlagMode.DISABLED and bucket < rollout_percent
        authoritative = mode in {
            FeatureFlagMode.CANARY,
            FeatureFlagMode.ACTIVE,
        }
        return FeatureFlagDecision(
            flag=normalized_flag,
            mode=mode,
            enabled=enabled,
            authoritative=authoritative,
            treatment=mode.value if enabled else FeatureFlagMode.DISABLED.value,
            rollout_percent=rollout_percent,
            bucket=bucket,
        )

    def snapshot(self, *, subject_id: object) -> dict[str, Any]:
        """返回可写入 Run/活动 payload 的四项开关审计快照。"""

        decisions = {
            flag.value: self.decision(flag, subject_id=subject_id).model_dump(
                mode="json"
            )
            for flag in AdaptiveLearningFlag
        }
        return {
            "policy_version": ADAPTIVE_LEARNING_FLAG_POLICY_VERSION,
            "subject_bucket_policy": "sha256(flag:subject)%100",
            "flags": decisions,
        }


adaptive_learning_flags = AdaptiveLearningFeatureFlags()


__all__ = [
    "ADAPTIVE_LEARNING_FLAG_POLICY_VERSION",
    "AdaptiveLearningFeatureFlags",
    "AdaptiveLearningFlag",
    "FeatureFlagDecision",
    "FeatureFlagMode",
    "adaptive_learning_flags",
]
