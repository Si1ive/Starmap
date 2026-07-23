"""conversation@v1：受控上下文路由、普通回答与路由前澄清。"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

from ..context_builder import AgentRunContext, ThreadContextBuilder
from ..model_runtime.answer import DirectAnswerDeps, direct_answer_runtime
from ..model_runtime.router import RouterDeps, router_runtime
from ..models import AgentRun
from ..service import AgentService
from .contracts import (
    ExecutionContext,
    Node,
    NodeResult,
    NodeStatus,
    WorkflowDefinition,
)
from .registry import workflow_registry

logger = get_logger(__name__)

CONVERSATION_ACTIONS = ("direct_answer", "clarify", "explain")


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
    context.charge_model_call()
    decision = await router_runtime.decide(
        agent_context.current_input,
        deps=RouterDeps(
            thread_id=agent_context.thread_id,
            user_id=agent_context.user_id,
            turn_id=agent_context.turn_id,
            allowed_actions=CONVERSATION_ACTIONS,
            token_budget=agent_context.token_budget,
        ),
        message_history=agent_context.to_message_history(),
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
    metadata["router_decision"] = decision.model_dump(exclude_none=True)
    run.metadata_json = metadata

    next_node = {
        "direct_answer": "direct_answer",
        "clarify": "clarify",
        "explain": "dispatch_explain",
    }[decision.action]
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
    context.charge_model_call()
    output = await direct_answer_runtime.answer(
        agent_context.current_input,
        deps=DirectAnswerDeps.from_context(agent_context),
        message_history=agent_context.to_message_history(),
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


async def _dispatch_explain_node(
    context: ExecutionContext,
    db: AsyncSession,
) -> NodeResult:
    """保持原讲解能力；其他业务 workflow 在下一阶段扩展。"""
    parent_run = await _load_run(context, db)
    if not parent_run:
        return NodeResult.failure("父 run 不存在，无法调度子工作流")
    child_run = await AgentService(db).create_run(
        user_id=parent_run.user_id,
        thread_id=parent_run.thread_id,
        workflow_name="explain",
        input_message=parent_run.input_message or context.get("input_message", ""),
        workflow_key="explain",
        workflow_version="v1",
        trigger_message_id=parent_run.trigger_message_id,
        parent_run_id=parent_run.id,
        root_run_id=parent_run.root_run_id or parent_run.id,
        presentation="compact",
        public_title="整理讲解",
    )
    return NodeResult.success(
        {
            "target_workflow": "explain@v1",
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
        max_model_calls=2,
    )
    nodes: list[tuple[str, str, Any, str]] = [
        ("route", "router", _route_node, "结合线程上下文判断下一步"),
        ("direct_answer", "action", _direct_answer_node, "生成普通回答"),
        ("clarify", "render", _clarify_node, "请求必要澄清"),
        ("dispatch_explain", "router", _dispatch_explain_node, "调度讲解链路"),
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
