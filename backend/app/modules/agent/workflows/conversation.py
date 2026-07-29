"""conversation@v1：受控上下文路由、普通回答与路由前澄清。"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

from ..capabilities import CapabilitySpec, capability_registry
from ..context_builder import AgentRunContext, ThreadContextBuilder
from ..events import event_store
from ..adaptive_learning_flags import (
    AdaptiveLearningFlag,
    FeatureFlagMode,
    adaptive_learning_flags,
)
from ..learning_snapshot import load_learning_snapshot_summary
from ..model_runtime.answer import DirectAnswerDeps, direct_answer_runtime
from ..model_runtime.referent import ReferentDeps, referent_runtime
from ..model_runtime.router import (
    RouterDeps,
    build_flag_disabled_conversation_decision,
    normalize_conversation_decision,
    router_runtime,
)
from ..model_runtime.teaching_policy import (
    TEACHING_POLICY_VERSION,
    freeze_teaching_policy,
)
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

CONVERSATION_ACTIONS = capability_registry.actions()


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
    learning_snapshot = await load_learning_snapshot_summary(
        db,
        snapshot_id=snapshot.id,
        user_id=run.user_id,
        thread_id=run.thread_id,
        active_topic=agent_context.active_topic,
    )
    known_knowledge_point_ids = tuple(
        dict.fromkeys(
            [
                *learning_snapshot.known_knowledge_point_ids,
                *(
                    topic.entity_id
                    for topic in understanding.topic_entities
                    if topic.entity_type == "knowledge_point" and topic.entity_id
                ),
            ]
        )
    )
    route_flag = adaptive_learning_flags.decision(
        AdaptiveLearningFlag.CONVERSATION_DECISION_V2,
        subject_id=run.user_id,
    )
    if route_flag.enabled:
        context.charge_model_call()
        v2_decision = await router_runtime.decide(
            understanding.standalone_request,
            deps=RouterDeps(
                thread_id=agent_context.thread_id,
                user_id=agent_context.user_id,
                turn_id=agent_context.turn_id,
                allowed_actions=CONVERSATION_ACTIONS,
                token_budget=agent_context.token_budget,
                conversation_summary=agent_context.conversation_summary,
                capabilities=capability_registry.model_manifest(CONVERSATION_ACTIONS),
                learning_snapshot=learning_snapshot.model_dump(mode="json"),
                read_tool_manifest=capability_registry.read_only_model_manifest(),
                allowed_read_tool_intents=(
                    capability_registry.allowed_read_tool_intents()
                ),
                known_knowledge_point_ids=known_knowledge_point_ids,
            ),
            message_history=agent_context.to_message_history(),
            db=db,
        )
        # shadow 只保存模型决策供评估，用户仍使用确定性兼容路径，避免灰度
        # 版本在未通过质量门槛前改变业务分支或产生子 Run。
        decision = (
            build_flag_disabled_conversation_decision(
                understanding.standalone_request,
                allowed_actions=CONVERSATION_ACTIONS,
            )
            if route_flag.mode is FeatureFlagMode.SHADOW
            else v2_decision
        )
    else:
        v2_decision = None
        decision = build_flag_disabled_conversation_decision(
            understanding.standalone_request,
            allowed_actions=CONVERSATION_ACTIONS,
        )
    decision = normalize_conversation_decision(decision)
    teaching_policy = freeze_teaching_policy(decision)
    context.set("agent_run_context", agent_context)
    context.set("learning_snapshot", learning_snapshot.model_dump(mode="json"))
    context.set("conversation_decision", decision)
    context.set("router_decision", decision)

    metadata = dict(run.metadata_json or {})
    metadata["context_audit"] = {
        "policy_version": agent_context.policy_version,
        "selected_message_ids": agent_context.selected_message_ids,
        "dropped_message_ids": agent_context.dropped_message_ids,
        "selected_artifact_ids": agent_context.selected_artifact_ids,
        "dropped_artifact_ids": agent_context.dropped_artifact_ids,
        "conversation_summary_id": (
            (agent_context.conversation_summary_source or {}).get("id")
        ),
        "estimated_tokens": agent_context.estimated_tokens,
        "token_budget": agent_context.token_budget,
    }
    metadata["memory_snapshot_id"] = snapshot.id
    metadata["turn_understanding"] = understanding.model_dump(mode="json")
    decision_payload = decision.model_dump(exclude_none=True)
    metadata["conversation_decision"] = decision_payload
    # 旧管理端和历史排障脚本继续读取 router_decision；两个键在同一事务中
    # 写入同一份结构化结果，避免兼容读取产生两个事实源。
    metadata["router_decision"] = decision_payload
    metadata["teaching_policy_version"] = TEACHING_POLICY_VERSION
    metadata["teaching_policy"] = teaching_policy.model_dump(mode="json")
    metadata["learning_snapshot"] = learning_snapshot.model_dump(mode="json")
    metadata["adaptive_learning_flags"] = adaptive_learning_flags.snapshot(
        subject_id=run.user_id
    )
    metadata["conversation_decision_rollout"] = {
        **route_flag.model_dump(mode="json"),
        "shadow_decision": (
            v2_decision.model_dump(exclude_none=True)
            if v2_decision is not None and route_flag.mode is FeatureFlagMode.SHADOW
            else None
        ),
    }
    metadata["read_capability_snapshot"] = (
        capability_registry.read_only_audit_manifest()
    )
    selected_capability = capability_registry.require(decision.action)
    metadata["capability_snapshot"] = {
        "policy_version": capability_registry.policy_version,
        "selected": selected_capability.key,
        "available": capability_registry.audit_manifest(CONVERSATION_ACTIONS),
    }
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
            "reason_codes": decision.reason_codes,
            "teaching_mode": decision.teaching_mode,
            "target_knowledge_point_ids": decision.target_knowledge_point_ids,
            "need_diagnostic_check": decision.need_diagnostic_check,
            "read_tool_intents": decision.read_tool_intents,
            "feature_flag_treatment": route_flag.treatment,
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
    decision = normalize_conversation_decision(context.get("router_decision"))
    output = await direct_answer_runtime.answer(
        agent_context.standalone_request or agent_context.current_input,
        deps=DirectAnswerDeps.from_context(
            agent_context,
            teaching_mode=decision.teaching_mode,
            need_diagnostic_check=decision.need_diagnostic_check,
        ),
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
    capability: CapabilitySpec,
    teaching_policy=None,
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
            "conversation_summary_id": (
                (agent_context.conversation_summary_source or {}).get("id")
            ),
        },
        "memory_snapshot_id": agent_context.memory_snapshot_id,
        "capability_snapshot": {
            "policy_version": capability_registry.policy_version,
            "selected": capability.key,
            "available": [capability.audit_descriptor()],
        },
        "adaptive_learning_flags": adaptive_learning_flags.snapshot(
            subject_id=agent_context.user_id
        ),
    }
    if teaching_policy is not None:
        policy_payload = teaching_policy.model_dump(mode="json")
        metadata["teaching_policy"] = policy_payload
        metadata["teaching_policy_version"] = policy_payload["policy_version"]
        metadata["conversation_decision"] = {
            "action": policy_payload["workflow_action"],
            "teaching_mode": policy_payload["teaching_mode"],
            "target_knowledge_point_ids": policy_payload["target_knowledge_point_ids"],
            "need_diagnostic_check": policy_payload["need_diagnostic_check"],
            "read_tool_intents": policy_payload["read_tool_intents"],
            "reason_codes": policy_payload["reason_codes"],
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
    if action not in {"explain", "validate", "grade", "plan"}:
        return NodeResult.failure(f"不支持的 workflow action: {action}")
    capability = capability_registry.require(action)
    agent_context = context.get("agent_run_context")
    if not isinstance(agent_context, AgentRunContext):
        return NodeResult.failure("缺少受控 AgentRunContext")
    decision = normalize_conversation_decision(context.get("router_decision"))
    teaching_policy = freeze_teaching_policy(decision)

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
        public_title=capability.title,
        metadata_json=_child_context_metadata(
            agent_context,
            model_config_id=(parent_run.metadata_json or {}).get("model_config_id"),
            capability=capability,
            teaching_policy=teaching_policy,
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
