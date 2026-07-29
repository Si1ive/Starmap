"""ConversationTutorAgent 教学策略的冻结与 child workflow 读取边界。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .schema import (
    ConversationDecision,
    ReadToolIntent,
    RouterAction,
    TeachingMode,
)

TEACHING_POLICY_VERSION = "conversation-tutor-v1"


class FrozenTeachingPolicy(BaseModel):
    """从 ConversationDecision 派生、供业务 child workflow 只读的策略事实。"""

    model_config = ConfigDict(extra="forbid")

    policy_version: str = TEACHING_POLICY_VERSION
    workflow_action: RouterAction
    teaching_mode: TeachingMode
    target_knowledge_point_ids: list[str] = Field(default_factory=list, max_length=32)
    need_diagnostic_check: bool = False
    read_tool_intents: list[ReadToolIntent] = Field(default_factory=list, max_length=3)
    reason_codes: list[str] = Field(default_factory=list, max_length=8)

    @classmethod
    def from_decision(cls, decision: ConversationDecision) -> "FrozenTeachingPolicy":
        """只复制策略字段，不把模型的公开话术或自由文本带入 child。"""

        teaching_mode = decision.teaching_mode or _default_teaching_mode(
            decision.action,
            need_diagnostic_check=decision.need_diagnostic_check,
        )
        return cls(
            workflow_action=decision.action,
            teaching_mode=teaching_mode,
            target_knowledge_point_ids=list(decision.target_knowledge_point_ids),
            need_diagnostic_check=decision.need_diagnostic_check,
            read_tool_intents=list(decision.read_tool_intents),
            reason_codes=list(decision.reason_codes),
        )


def _default_teaching_mode(
    action: RouterAction,
    *,
    need_diagnostic_check: bool = False,
) -> TeachingMode:
    if need_diagnostic_check and action in {"direct_answer", "explain"}:
        return "explain_then_micro_check"
    return {
        "direct_answer": "answer_only",
        "clarify": "clarify",
        "explain": "explain",
        "validate": "practice_weakness",
        "grade": "feedback",
        "plan": "plan",
    }[action]


def load_frozen_teaching_policy(
    context: Any,
    *,
    workflow_action: RouterAction,
) -> FrozenTeachingPolicy:
    """从 Worker 注入的 Run metadata 读取策略，兼容没有策略的旧 child Run。

    如果是旧 Run 或单测直接启动 workflow，则按该 workflow 的固定默认模式生成
    只读内存值；不会回写数据库，也不会让 child workflow 重新调用 Router。
    """

    raw_policy = context.get("teaching_policy")
    if isinstance(raw_policy, FrozenTeachingPolicy):
        policy = raw_policy
    elif isinstance(raw_policy, dict):
        policy = FrozenTeachingPolicy.model_validate(raw_policy)
    else:
        decision = context.get("conversation_decision") or context.get(
            "router_decision"
        )
        if isinstance(decision, dict):
            decision = ConversationDecision.model_validate(decision)
        if isinstance(decision, ConversationDecision):
            policy = FrozenTeachingPolicy.from_decision(decision)
        else:
            policy = FrozenTeachingPolicy(
                workflow_action=workflow_action,
                teaching_mode=_default_teaching_mode(workflow_action),
                reason_codes=[f"legacy_{workflow_action}_run"],
            )
    if policy.workflow_action != workflow_action:
        raise ValueError(
            "child workflow 的 teaching policy action 与实际 workflow 不一致"
        )
    return policy


def freeze_teaching_policy(
    decision: ConversationDecision,
) -> FrozenTeachingPolicy:
    """在 conversation route 成功后生成可放入 Run metadata 的策略副本。"""

    return FrozenTeachingPolicy.from_decision(decision)


__all__ = [
    "TEACHING_POLICY_VERSION",
    "FrozenTeachingPolicy",
    "freeze_teaching_policy",
    "load_frozen_teaching_policy",
]
