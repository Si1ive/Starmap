"""conversation@v1：受控上下文路由、普通回答与路由前澄清。"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

from ..context_builder import AgentRunContext, ThreadContextBuilder
from ..events import event_store
from ..model_runtime.answer import DirectAnswerDeps, direct_answer_runtime
from ..model_runtime.referent import ReferentDeps, referent_runtime
from ..model_runtime.router import ROUTER_ACTIONS, RouterDeps, router_runtime
from ..models import AgentRun
from ..service import AgentService
from ..timeline import AgentTimelineService
from ..turn_understanding import (
    apply_referent_resolution,
    build_ambiguous_referent_candidates,
    build_turn_understanding,
    ensure_turn_memory_snapshot,
    hydrate_referent_candidate_labels,
)
from .contracts import (
    ExecutionContext,
    Node,
    NodeResult,
    NodeStatus,
    WorkflowDefinition,
)
from .registry import workflow_registry

logger = get_logger(__name__)

CONVERSATION_ACTIONS = ROUTER_ACTIONS
WORKFLOW_ROUTES = {
    "explain": {"title": "整理讲解"},
    "validate": {"title": "生成专项练习"},
    "grade": {"title": "分析作答"},
    "plan": {"title": "调整学习计划"},
}


async def _load_run(context: ExecutionContext, db: AsyncSession) -> AgentRun | None:
    result = await db.execute(select(AgentRun).where(AgentRun.id == context.run_id))
    return result.scalar_one_or_none()


async def _route_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """从可信线程事实构建上下文，并由 Pydantic AI Router 决定下一步。"""
    run = await _load_run(context, db)
    if not run:
        return NodeResult.failure("conversation run 不存在")

    agent_context = await ThreadContextBuilder(db).build(
        user_id=run.user_id,
        thread_id=run.thread_id,
        turn_id=run.id,
        current_message_id=run.trigger_message_id,
        token_budget=4096,
    )
    understanding = build_turn_understanding(agent_context)
    referent_candidates = build_ambiguous_referent_candidates(
        agent_context,
        understanding,
    )
    referent_candidates = await hydrate_referent_candidate_labels(
        db,
        referent_candidates,
    )
    if referent_candidates:
        context.charge_model_call()
        resolution = await referent_runtime.resolve(
            understanding.raw_input,
            candidates=referent_candidates,
            deps=ReferentDeps(
                thread_id=agent_context.thread_id,
                user_id=agent_context.user_id,
                turn_id=agent_context.turn_id,
            ),
            message_history=agent_context.to_message_history(),
            db=db,
        )
        understanding = apply_referent_resolution(
            understanding,
            candidates=referent_candidates,
            resolution=resolution,
        )
    snapshot = await ensure_turn_memory_snapshot(
        db,
        run=run,
        agent_context=agent_context,
        understanding=understanding,
    )
    agent_context.standalone_request = understanding.standalone_request
    agent_context.memory_snapshot_id = snapshot.id
    agent_context.memory_state_version = snapshot.state_version
    if understanding.topic_entities:
        agent_context.active_topic = understanding.topic_entities[0].model_dump(
            mode="json"
        )
    context.charge_model_call()
    decision = await router_runtime.decide(
        understanding.standalone_request,
        deps=RouterDeps(
            thread_id=agent_context.thread_id,
            user_id=agent_context.user_id,
            turn_id=agent_context.turn_id,
            allowed_actions=CONVERSATION_ACTIONS,
            token_budget=agent_context.token_budget,
        ),
        message_history=agent_context.to_message_history(),
        db=db,
    )
    context.set("agent_run_context", agent_context)
    context.set("router_decision", decision)

    metadata = dict(run.metadata_json or {})
    metadata["context_audit"] = {
        "policy_version": agent_context.policy_version,
        "selected_message_ids": agent_context.selected_message_ids,
        "dropped_message_ids": agent_context.dropped_message_ids,
        "selected_artifact_ids": agent_context.selected_artifact_ids,
        "dropped_artifact_ids": agent_context.dropped_artifact_ids,
        "estimated_tokens": agent_context.estimated_tokens,
        "token_budget": agent_context.token_budget,
    }
    metadata["memory_snapshot_id"] = snapshot.id
    metadata["turn_understanding"] = understanding.model_dump(mode="json")
    metadata["router_decision"] = decision.model_dump(exclude_none=True)
    run.metadata_json = metadata

    next_node = {
        "direct_answer": "direct_answer",
        "clarify": "clarify",
    }.get(decision.action, "dispatch_workflow")
    logger.info(
        "conversation 动态路由完成",
        run_id=run.id,
        action=decision.action,
        reason_code=decision.reason_code,
    )
    return NodeResult.success(
        {
            "action": decision.action,
            "confidence": decision.confidence,
            "reason_code": decision.reason_code,
        },
        next_node=next_node,
    )


async def _direct_answer_node(
    context: ExecutionContext,
    db: AsyncSession,
) -> NodeResult:
    """在同一静默 conversation run 中生成普通回答。"""
    agent_context = context.get("agent_run_context")
    if not isinstance(agent_context, AgentRunContext):
        return NodeResult.failure("缺少受控 AgentRunContext")

    async def publish_delta(delta: str) -> None:
        await event_store.append(
            db,
            context.run_id,
            "message.delta",
            {"run_id": context.run_id, "delta": delta},
        )
        # stream_output 已按 100ms 聚合；这里提交后独立 SSE session 才能
        # 读取增量，不能只 flush 后等待整个回答完成。
        await db.commit()

    context.charge_model_call()
    output = await direct_answer_runtime.answer(
        agent_context.standalone_request or agent_context.current_input,
        deps=DirectAnswerDeps.from_context(agent_context),
        message_history=agent_context.to_message_history(),
        db=db,
        on_delta=publish_delta,
    )
    return NodeResult(
        status=NodeStatus.COMPLETED,
        output={"answer_summary": output.public_summary},
        next_node="completed",
        artifact={
            "type": "message",
            "title": "回答",
            "content": output.content,
            "summary": output.public_summary,
        },
    )


async def _clarify_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """直接输出 Router 生成的澄清问题，不创建可见 workflow。"""
    decision = context.get("router_decision")
    question = getattr(decision, "clarification_question", None)
    if not question:
        return NodeResult.failure("clarify 路由缺少澄清问题")
    return NodeResult(
        status=NodeStatus.COMPLETED,
        output={"clarification_question": question},
        next_node="completed",
        artifact={
            "type": "message",
            "title": "需要补充信息",
            "content": question,
        },
    )


def _child_context_metadata(
    agent_context: AgentRunContext,
    *,
    model_config_id: str | None,
) -> dict[str, Any]:
    """只向 child run 传递经过上下文策略筛选后的引用和审计信息。"""
    metadata = {
        "context_policy_version": agent_context.policy_version,
        "context_snapshot": {
            "selected_message_ids": agent_context.selected_message_ids,
            "selected_artifact_ids": agent_context.selected_artifact_ids,
            "attachment_refs": agent_context.attachments,
            "context_refs": agent_context.context_refs,
            "pending_interaction_ids": [
                item.id for item in agent_context.pending_interactions
            ],
            "permission_scope": agent_context.permission_scope.model_dump(),
            "estimated_tokens": agent_context.estimated_tokens,
            "token_budget": agent_context.token_budget,
            "active_topic": agent_context.active_topic,
            "standalone_request": agent_context.standalone_request,
        },
        "memory_snapshot_id": agent_context.memory_snapshot_id,
    }
    if model_config_id:
        metadata["model_config_id"] = model_config_id
    return metadata


async def _dispatch_workflow_node(
    context: ExecutionContext,
    db: AsyncSession,
) -> NodeResult:
    """按 Router action 幂等创建业务 child run 和对话内 workflow 项。"""
    parent_run = await _load_run(context, db)
    if not parent_run:
        return NodeResult.failure("父 run 不存在，无法调度子工作流")
    action = context.get("action")
    route = WORKFLOW_ROUTES.get(action)
    if not route:
        return NodeResult.failure(f"不支持的 workflow action: {action}")
    agent_context = context.get("agent_run_context")
    if not isinstance(agent_context, AgentRunContext):
        return NodeResult.failure("缺少受控 AgentRunContext")

    child_run = await AgentService(db).create_run(
        user_id=parent_run.user_id,
        thread_id=parent_run.thread_id,
        workflow_name=action,
        input_message=(
            agent_context.standalone_request
            or parent_run.input_message
            or context.get("input_message", "")
        ),
        client_idempotency_key=f"dispatch:{parent_run.id}:{action}",
        workflow_key=action,
        workflow_version="v1",
        trigger_message_id=parent_run.trigger_message_id,
        parent_run_id=parent_run.id,
        root_run_id=parent_run.root_run_id or parent_run.id,
        presentation="compact",
        public_title=route["title"],
        metadata_json=_child_context_metadata(
            agent_context,
            model_config_id=(parent_run.metadata_json or {}).get("model_config_id"),
        ),
    )
    await AgentTimelineService(db).ensure_workflow_item(
        thread_id=parent_run.thread_id,
        root_run_id=parent_run.root_run_id or parent_run.id,
        run_id=child_run.id,
    )
    return NodeResult.success(
        {
            "target_workflow": f"{action}@v1",
            "child_run_id": child_run.id,
        },
        next_node="completed",
    )


async def _completed_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """结束内部 conversation run，不生成额外报告式消息。"""
    return NodeResult.success(
        {
            "workflow": "conversation@v1",
            "action": context.get("action"),
            "child_run_id": context.get("child_run_id"),
        }
    )


def build_conversation_workflow() -> WorkflowDefinition:
    workflow = WorkflowDefinition(
        name="conversation",
        version="v1",
        entry_node="route",
        max_model_calls=3,
    )
    nodes: list[tuple[str, str, Any, str]] = [
        ("route", "router", _route_node, "结合线程上下文判断下一步"),
        ("direct_answer", "action", _direct_answer_node, "生成普通回答"),
        ("clarify", "render", _clarify_node, "请求必要澄清"),
        ("dispatch_workflow", "router", _dispatch_workflow_node, "调度业务链路"),
        ("completed", "render", _completed_node, "完成"),
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


workflow_registry.register(build_conversation_workflow())
