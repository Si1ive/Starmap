"""learning_observation@v1：静默观察一轮已完成的根 conversation。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..learning_observer import (
    build_observer_input_snapshot,
    record_turn_observation,
)
from ..model_runtime.observer import (
    OBSERVER_VERSION,
    LearningObserverDeps,
    TurnObservationOutput,
    learning_observer_runtime,
)
from ..models import AgentRun
from .contracts import ExecutionContext, Node, NodeResult, WorkflowDefinition
from .registry import workflow_registry


async def _load_run(context: ExecutionContext, db: AsyncSession) -> AgentRun | None:
    return await db.scalar(
        select(AgentRun).where(
            AgentRun.id == context.run_id,
            AgentRun.user_id == context.user_id,
        )
    )


async def _prepare_observation_node(
    context: ExecutionContext,
    db: AsyncSession,
) -> NodeResult:
    run = await _load_run(context, db)
    if run is None or run.presentation != "silent":
        return NodeResult.failure("LearningObserver run 不存在或不是 silent")
    snapshot = await build_observer_input_snapshot(db, observer_run=run)
    metadata = dict(run.metadata_json or {})
    metadata["observer_input_snapshot"] = snapshot
    metadata["observer_input_policy_version"] = snapshot["policy_version"]
    run.metadata_json = metadata
    return NodeResult.success(
        {"observer_input_snapshot": snapshot},
        next_node="observe_turn",
    )


async def _observe_turn_node(
    context: ExecutionContext,
    db: AsyncSession,
) -> NodeResult:
    run = await _load_run(context, db)
    snapshot = context.get("observer_input_snapshot")
    if run is None or not isinstance(snapshot, dict):
        return NodeResult.failure("LearningObserver 缺少冻结输入快照")
    metadata = run.metadata_json if isinstance(run.metadata_json, dict) else {}
    source_run_id = str(metadata.get("source_run_id") or "").strip()
    source_message_id = str(metadata.get("source_message_id") or "").strip()
    candidate_ids = tuple(
        str(item.get("knowledge_point_id"))
        for item in snapshot.get("knowledge_point_candidates") or []
        if isinstance(item, dict) and item.get("knowledge_point_id")
    )
    context.charge_model_call()
    output = await learning_observer_runtime.observe(
        snapshot,
        deps=LearningObserverDeps(
            run_id=run.id,
            source_run_id=source_run_id,
            user_id=run.user_id,
            thread_id=run.thread_id,
            source_message_id=source_message_id,
            knowledge_point_ids=candidate_ids,
        ),
        db=db,
    )
    metadata = dict(run.metadata_json or {})
    metadata["turn_observation"] = output.model_dump(mode="json")
    metadata["observer_version"] = OBSERVER_VERSION
    run.metadata_json = metadata
    return NodeResult.success(
        {"turn_observation": output.model_dump(mode="json")},
        next_node="project_observation",
    )


async def _project_observation_node(
    context: ExecutionContext,
    db: AsyncSession,
) -> NodeResult:
    run = await _load_run(context, db)
    snapshot = context.get("observer_input_snapshot")
    raw_output = context.get("turn_observation")
    if (
        run is None
        or not isinstance(snapshot, dict)
        or not isinstance(raw_output, dict)
    ):
        return NodeResult.failure("LearningObserver 缺少可投影的结构化输出")
    output = TurnObservationOutput.model_validate(raw_output)
    event = await record_turn_observation(
        db,
        observer_run=run,
        input_snapshot=snapshot,
        output=output,
    )
    return NodeResult.success(
        {
            "learning_activity_event_id": event.id,
            "evidence_id": event.source_id,
        },
        next_node="completed",
    )


async def _completed_node(
    context: ExecutionContext,
    db: AsyncSession,
) -> NodeResult:
    return NodeResult.success(
        {
            "workflow": "learning_observation@v1",
            "learning_activity_event_id": context.get("learning_activity_event_id"),
        }
    )


def build_learning_observation_workflow() -> WorkflowDefinition:
    workflow = WorkflowDefinition(
        name="learning_observation",
        version="v1",
        entry_node="prepare_observation",
        max_model_calls=1,
    )
    nodes: list[tuple[str, str, Any, str]] = [
        (
            "prepare_observation",
            "action",
            _prepare_observation_node,
            "读取并冻结来源对话快照",
        ),
        (
            "observe_turn",
            "action",
            _observe_turn_node,
            "结构化提取学习行为与诊断假设",
        ),
        (
            "project_observation",
            "action",
            _project_observation_node,
            "经证据门禁写入非掌握度活动事实",
        ),
        ("completed", "render", _completed_node, "完成静默观察"),
    ]
    for name, node_type, execute, description in nodes:
        workflow.add_node(
            Node(
                name=name,
                node_type=node_type,
                execute=execute,
                description=description,
            )
        )
    return workflow


workflow_registry.register(build_learning_observation_workflow())
