"""ConversationTutorAgent 教学策略和只读快照边界测试。"""

import pytest
from pydantic import ValidationError

from app.modules.agent.learning_snapshot import LearningSnapshotSummary
from app.modules.agent.capabilities import capability_registry
from app.modules.agent.context_builder import AgentRunContext, PermissionScope
from app.modules.agent.model_runtime.schema import ConversationDecision
from app.modules.agent.model_runtime.teaching_policy import (
    FrozenTeachingPolicy,
    load_frozen_teaching_policy,
)
from app.modules.agent.workflows.contracts import ExecutionContext
from app.modules.agent.workflows.conversation import _child_context_metadata


def test_learning_snapshot_summary_exposes_only_frozen_knowledge_point_ids():
    summary = LearningSnapshotSummary(
        snapshot_id="snapshot_001",
        state_version=3,
        active_topic={
            "entity_type": "knowledge_point",
            "entity_id": "kp_binary_search",
            "title": "二分查找",
        },
        mastery_signals=[
            {"knowledge_point_id": "kp_binary_search", "effective_mastery_score": 0.4},
            {"knowledge_point_id": "kp_queue", "effective_mastery_score": 0.8},
        ],
    )

    assert summary.known_knowledge_point_ids == (
        "kp_binary_search",
        "kp_queue",
    )

    with pytest.raises(ValidationError):
        LearningSnapshotSummary(snapshot_id="snapshot_001", mastery_score=0.2)


def test_teaching_policy_freezes_strategy_without_model_write_fields():
    decision = ConversationDecision(
        action="validate",
        confidence=0.9,
        reason_code="weak_topic",
        teaching_mode="practice_weakness",
        target_knowledge_point_ids=["kp_binary_search"],
        need_diagnostic_check=True,
        read_tool_intents=["get_learning_snapshot"],
    )

    policy = FrozenTeachingPolicy.from_decision(decision)

    assert policy.workflow_action == "validate"
    assert policy.teaching_mode == "practice_weakness"
    assert policy.target_knowledge_point_ids == ["kp_binary_search"]
    assert policy.read_tool_intents == ["get_learning_snapshot"]
    assert "mastery_score" not in policy.model_dump()


def test_child_workflow_reads_frozen_policy_and_does_not_reselect_action():
    context = ExecutionContext("run_001", "user_001", object())
    context.set(
        "teaching_policy",
        {
            "policy_version": "conversation-tutor-v1",
            "workflow_action": "explain",
            "teaching_mode": "explain_then_micro_check",
            "target_knowledge_point_ids": ["kp_binary_search"],
            "need_diagnostic_check": True,
            "read_tool_intents": ["retrieve_knowledge"],
            "reason_codes": ["uncertain_concept"],
        },
    )

    policy = load_frozen_teaching_policy(context, workflow_action="explain")

    assert policy.teaching_mode == "explain_then_micro_check"
    assert policy.need_diagnostic_check is True
    with pytest.raises(ValueError, match="action 与实际 workflow 不一致"):
        load_frozen_teaching_policy(context, workflow_action="validate")


def test_legacy_child_without_policy_uses_workflow_default():
    context = ExecutionContext("run_001", "user_001", object())

    policy = load_frozen_teaching_policy(context, workflow_action="grade")

    assert policy.teaching_mode == "feedback"
    assert policy.reason_codes == ["legacy_grade_run"]


def test_child_metadata_freezes_tutor_strategy_next_to_context_snapshot():
    context = AgentRunContext(
        thread_id="thread_001",
        user_id="user_001",
        turn_id="run_001",
        current_message_id="message_001",
        current_input="给我讲解二分查找",
        permission_scope=PermissionScope(
            user_id="user_001",
            thread_id="thread_001",
            root_run_id="run_001",
        ),
        token_budget=4096,
        history_token_budget=4096,
        estimated_tokens=10,
    )
    decision = ConversationDecision(
        action="explain",
        confidence=0.9,
        reason_code="uncertain_concept",
        teaching_mode="explain_then_micro_check",
        need_diagnostic_check=True,
        target_knowledge_point_ids=["kp_binary_search"],
    )

    metadata = _child_context_metadata(
        context,
        model_config_id=None,
        capability=capability_registry.require("explain"),
        teaching_policy=FrozenTeachingPolicy.from_decision(decision),
    )

    assert metadata["teaching_policy_version"] == "conversation-tutor-v1"
    assert metadata["teaching_policy"]["teaching_mode"] == ("explain_then_micro_check")
    assert metadata["conversation_decision"]["target_knowledge_point_ids"] == [
        "kp_binary_search"
    ]
