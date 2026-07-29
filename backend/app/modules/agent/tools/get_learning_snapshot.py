"""只读读取当前 Agent Run 已冻结的 LearningSnapshot。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..learning_snapshot import LearningSnapshotSummary, load_learning_snapshot_summary
from ..models import AgentRun
from .registry import ToolRegistry, ToolSpec


async def _load_owned_run(db: AsyncSession, run_id: str | None) -> AgentRun:
    normalized = str(run_id or "").strip()
    if not normalized:
        raise ValueError("读取 LearningSnapshot 需要服务端注入 run_id")
    run = await db.scalar(select(AgentRun).where(AgentRun.id == normalized))
    if run is None:
        raise ValueError("Agent Run 不存在")
    return run


async def get_learning_snapshot(
    db: AsyncSession,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """通过 Run 所有权读取快照，不接受客户端 user_id 或 snapshot_id。"""

    run = await _load_owned_run(db, run_id)
    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    context_snapshot = (
        metadata.get("context_snapshot")
        if isinstance(metadata.get("context_snapshot"), dict)
        else {}
    )
    active_topic = (
        context_snapshot.get("active_topic")
        if isinstance(context_snapshot.get("active_topic"), dict)
        else None
    )
    summary = await load_learning_snapshot_summary(
        db,
        snapshot_id=metadata.get("memory_snapshot_id"),
        user_id=run.user_id,
        thread_id=run.thread_id,
        active_topic=active_topic,
    )
    if not isinstance(summary, LearningSnapshotSummary):
        raise ValueError("LearningSnapshot 读取结果无效")
    return {
        "status": "success",
        **summary.model_dump(mode="json"),
        "run_id": run.id,
    }


_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {},
    "required": [],
}


def register_get_learning_snapshot(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="get_learning_snapshot",
            description="读取当前 Run 已冻结的掌握度、证据、薄弱点和诊断需求。",
            parameters=_TOOL_PARAMETERS,
            execute=get_learning_snapshot,
            read_only=True,
            allowed_workflows=("conversation", "explain", "validate", "grade", "plan"),
            injected_parameters=("run_id",),
        )
    )


__all__ = ["get_learning_snapshot", "register_get_learning_snapshot"]
