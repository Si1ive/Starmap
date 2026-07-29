"""解释后微诊断题的幂等调度与来源回链。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .capabilities import capability_registry
from .models import AgentArtifact, AgentRun
from .model_runtime.teaching_policy import FrozenTeachingPolicy
from .service import AgentService
from .state_machine import RunStatus
from .timeline import AgentTimelineService

DIAGNOSTIC_CHECK_VERSION = "diagnostic-check-v1"


def _context_snapshot(source_run: AgentRun, metadata: dict[str, Any]) -> dict[str, Any]:
    raw = metadata.get("context_snapshot")
    if isinstance(raw, dict):
        return dict(raw)
    learning_snapshot = metadata.get("learning_snapshot")
    active_topic = (
        learning_snapshot.get("active_topic")
        if isinstance(learning_snapshot, dict)
        else None
    )
    return {
        "active_topic": active_topic,
        "selected_message_ids": list(
            (metadata.get("context_audit") or {}).get("selected_message_ids") or []
        ),
        "selected_artifact_ids": list(
            (metadata.get("context_audit") or {}).get("selected_artifact_ids") or []
        ),
    }


async def schedule_diagnostic_check(
    db: AsyncSession,
    *,
    source_run: AgentRun,
    source_artifact: AgentArtifact | None = None,
) -> AgentRun | None:
    """为 ``explain_then_micro_check`` 创建一个 Validate child Run。

    只有根 conversation 的 direct answer 或其 explain child 可以触发；Validate、Grade
    和 Observer 不会递归创建诊断题。稳定幂等键保证 Worker 重试不会生成第二个练习会话。
    """

    if source_run.status != RunStatus.COMPLETED.value:
        return None
    if source_run.workflow_name not in {"conversation", "explain"}:
        return None

    metadata = (
        source_run.metadata_json if isinstance(source_run.metadata_json, dict) else {}
    )
    raw_policy = metadata.get("teaching_policy")
    if not isinstance(raw_policy, dict):
        return None
    if raw_policy.get("teaching_mode") != "explain_then_micro_check":
        return None
    if source_run.workflow_name == "conversation":
        if raw_policy.get("workflow_action") != "direct_answer":
            return None
    elif raw_policy.get("workflow_action") != "explain":
        return None

    context_snapshot = _context_snapshot(source_run, metadata)
    active_topic = context_snapshot.get("active_topic")
    target_ids = list(
        dict.fromkeys(
            str(value).strip()
            for value in raw_policy.get("target_knowledge_point_ids") or []
            if str(value).strip()
        )
    )
    if (
        not target_ids
        and isinstance(active_topic, dict)
        and active_topic.get("entity_type") == "knowledge_point"
        and active_topic.get("entity_id")
    ):
        target_ids = [str(active_topic["entity_id"]).strip()]
    if not target_ids:
        return None

    topic_title = (
        str(active_topic.get("title") or "").strip()
        if isinstance(active_topic, dict)
        else ""
    )
    diagnostic_context = {
        "kind": "micro_check",
        "version": DIAGNOSTIC_CHECK_VERSION,
        "source_run_id": source_run.id,
        "source_artifact_id": source_artifact.id if source_artifact else None,
        "target_knowledge_point_ids": target_ids,
        "topic_title": topic_title or None,
    }
    capability_registry.require("validate")
    diagnostic_policy = FrozenTeachingPolicy(
        workflow_action="validate",
        teaching_mode="practice_weakness",
        target_knowledge_point_ids=target_ids,
        need_diagnostic_check=True,
        read_tool_intents=["search_question_candidates"],
        reason_codes=["diagnostic_micro_check", "explain_then_micro_check"],
    )
    child_metadata: dict[str, Any] = {
        "context_policy_version": metadata.get(
            "context_policy_version", "agent-context-v1"
        ),
        "context_snapshot": context_snapshot,
        "memory_snapshot_id": metadata.get("memory_snapshot_id"),
        "diagnostic_context": diagnostic_context,
        "diagnostic_source_run_id": source_run.id,
        "diagnostic_source_artifact_id": diagnostic_context["source_artifact_id"],
        "diagnostic_target_knowledge_point_ids": target_ids,
        "teaching_policy": diagnostic_policy.model_dump(mode="json"),
        "teaching_policy_version": diagnostic_policy.policy_version,
        "conversation_decision": {
            "action": "validate",
            "confidence": 1.0,
            "reason_code": "diagnostic_micro_check",
            "reason_codes": diagnostic_policy.reason_codes,
            "teaching_mode": diagnostic_policy.teaching_mode,
            "target_knowledge_point_ids": target_ids,
            "need_diagnostic_check": True,
            "read_tool_intents": diagnostic_policy.read_tool_intents,
        },
    }
    if metadata.get("model_config_id"):
        child_metadata["model_config_id"] = metadata["model_config_id"]

    title = f"{topic_title}诊断检查" if topic_title else "解释后诊断检查"
    child_run = await AgentService(db).create_run(
        user_id=source_run.user_id,
        thread_id=source_run.thread_id,
        workflow_name="validate",
        input_message=f"围绕{topic_title or '当前知识点'}完成一次短诊断检查",
        client_idempotency_key=(
            f"diagnostic:{source_run.id}:{DIAGNOSTIC_CHECK_VERSION}"
        ),
        workflow_key="validate",
        workflow_version="v1",
        trigger_message_id=source_run.trigger_message_id,
        parent_run_id=source_run.id,
        root_run_id=source_run.root_run_id or source_run.id,
        presentation="compact",
        public_title=title,
        metadata_json=child_metadata,
    )
    await AgentTimelineService(db).ensure_workflow_item(
        thread_id=source_run.thread_id,
        root_run_id=source_run.root_run_id or source_run.id,
        run_id=child_run.id,
    )
    return child_run


__all__ = ["DIAGNOSTIC_CHECK_VERSION", "schedule_diagnostic_check"]
