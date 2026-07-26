"""把可信记忆事实物化为可选择的长期记忆项。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .memory_contracts import MemoryFactType
from .models import AgentArtifact, AgentMemoryEvent, AgentMemoryItem


async def _upsert_memory_item(
    db: AsyncSession,
    event: AgentMemoryEvent,
    *,
    scope: str,
    thread_id: str | None,
    item_type: str,
    content_text: str,
    metadata: dict,
    source_snapshot_id: str | None,
) -> None:
    query = select(AgentMemoryItem).where(
        AgentMemoryItem.user_id == event.user_id,
        AgentMemoryItem.scope == scope,
        AgentMemoryItem.item_type == item_type,
        AgentMemoryItem.item_key == event.idempotency_key,
    )
    if thread_id is None:
        query = query.where(AgentMemoryItem.thread_id.is_(None))
    else:
        query = query.where(AgentMemoryItem.thread_id == thread_id)
    item = await db.scalar(query)
    if item is None:
        item = AgentMemoryItem(
            id=f"memitem_{uuid.uuid4().hex[:20]}",
            user_id=event.user_id,
            thread_id=thread_id,
            scope=scope,
            item_type=item_type,
            item_key=event.idempotency_key,
            status="active",
            content_text=content_text,
            metadata_json=metadata,
            source_snapshot_id=source_snapshot_id,
            last_confirmed_run_id=event.run_id,
        )
        db.add(item)
    else:
        item.status = "active"
        item.content_text = content_text
        item.metadata_json = metadata
        item.source_snapshot_id = source_snapshot_id
        item.last_confirmed_run_id = event.run_id
    await db.flush()


async def _project_topic_context(
    db: AsyncSession,
    event: AgentMemoryEvent,
) -> None:
    if event.memory_scope != "thread" or not event.thread_id:
        raise ValueError("topic_confirmed 必须是线程级事实")
    topic = event.payload_json.get("topic") or {}
    title = str(topic.get("title") or "").strip()
    if not title:
        raise ValueError("topic_confirmed 缺少主题标题")
    aliases = [
        str(alias).strip()
        for alias in topic.get("aliases") or []
        if str(alias).strip()
    ]
    await _upsert_memory_item(
        db,
        event,
        scope="thread",
        thread_id=event.thread_id,
        item_type="topic_context",
        content_text=title,
        metadata={
            "source_memory_event_id": event.id,
            "fact_type": event.fact_type,
            "entity_type": topic.get("entity_type"),
            "entity_id": topic.get("entity_id"),
            "aliases": aliases,
        },
        source_snapshot_id=event.payload_json.get("snapshot_id"),
    )


def _render_plan_goal_text(title: str, goals: list) -> str:
    lines = [title]
    for goal in goals:
        if isinstance(goal, dict):
            subject = str(goal.get("subject") or "").strip()
            target = str(goal.get("target") or "").strip()
            if subject and target:
                lines.append(f"{subject}：{target}")
            elif subject or target:
                lines.append(subject or target)
        elif str(goal).strip():
            lines.append(str(goal).strip())
    return "\n".join(lines)


async def _project_confirmed_plan_goal(
    db: AsyncSession,
    event: AgentMemoryEvent,
) -> None:
    if event.memory_scope != "user" or event.source_kind != "artifact":
        raise ValueError("plan_confirmed 必须是用户级 Artifact 事实")
    payload = event.payload_json or {}
    artifact_id = str(payload.get("artifact_id") or "").strip()
    approval_id = str(payload.get("approval_id") or "").strip()
    artifact = await db.scalar(
        select(AgentArtifact).where(
            AgentArtifact.id == artifact_id,
            AgentArtifact.run_id == event.run_id,
            AgentArtifact.artifact_type == "plan",
        )
    )
    if artifact is None:
        raise ValueError("plan_confirmed 找不到同 Run 的计划 Artifact")
    artifact_content = artifact.content_json or {}
    if not approval_id or artifact_content.get("approval_id") != approval_id:
        raise ValueError("plan_confirmed 的审批来源与 Artifact 不匹配")
    content = artifact_content.get("content") or {}
    goals = content.get("goals") or []
    if not isinstance(goals, list) or not goals:
        raise ValueError("plan_confirmed 的计划 Artifact 缺少目标")
    title = str(artifact_content.get("title") or "学习计划").strip()
    await _upsert_memory_item(
        db,
        event,
        scope="user",
        thread_id=None,
        item_type="learning_goal",
        content_text=_render_plan_goal_text(title, goals),
        metadata={
            "source_memory_event_id": event.id,
            "fact_type": event.fact_type,
            "artifact_id": artifact.id,
            "approval_id": approval_id,
            "period": content.get("period"),
            "goal_count": len(goals),
            "goals": goals,
        },
        source_snapshot_id=payload.get("memory_snapshot_id"),
    )


async def project_trusted_memory_event(
    db: AsyncSession,
    event: AgentMemoryEvent,
) -> None:
    """按事实类型执行最小派生；不复制 Explain/Practice/Grade 的权威正文。"""
    try:
        fact_type = MemoryFactType(event.fact_type)
    except ValueError as error:
        raise ValueError(f"不支持的记忆事实类型: {event.fact_type}") from error
    if fact_type is MemoryFactType.TOPIC_CONFIRMED:
        await _project_topic_context(db, event)
    elif fact_type is MemoryFactType.PLAN_CONFIRMED:
        await _project_confirmed_plan_goal(db, event)
