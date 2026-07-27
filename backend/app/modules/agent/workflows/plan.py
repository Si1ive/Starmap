"""
plan@v1 工作流（学习计划，简化版）

aggregate_learning_evidence -> planning_precondition_gate -> propose_plan_delta ->
plan_quality_gate -> create_approval -> wait_for_approval -> apply_plan_change -> render_plan_result -> completed
"""

import json as _json

from typing import Dict, Any, Optional, List
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, Node, NodeResult, NodeStatus, ExecutionContext
from .registry import workflow_registry
from ..model_runtime.adapter import model_adapter
from ..memory_selector import load_planning_bundle
from ..state_machine import RunStatus, state_machine
from ..time_utils import utc_now

logger = get_logger(__name__)


async def _aggregate_learning_evidence_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """聚合学习证据"""
    bundle = await load_planning_bundle(
        db,
        run_id=context.run_id,
        user_id=context.user_id,
    )
    evidence = {
        "user_id": context.user_id,
        "targets": [target.model_dump(mode="json") for target in bundle.targets],
        "weak_areas": [target.title for target in bundle.targets],
        "period": bundle.period,
        "learning_goal_item_ids": bundle.learning_goal_item_ids,
        "mastery_signals": bundle.mastery_signals,
        "preferences": bundle.preferences,
        "preference_sources": [
            source.model_dump(mode="json") for source in bundle.preference_sources
        ],
    }
    context.set("planning_bundle", bundle.model_dump(mode="json"))
    context.set("learning_evidence", evidence)
    logger.info(
        "学习证据聚合",
        run_id=context.run_id,
        user_id=context.user_id,
        target_count=len(bundle.targets),
    )
    return NodeResult.success({"evidence_aggregated": True}, next_node="planning_precondition_gate")


async def _planning_precondition_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """前置条件校验"""
    evidence = context.get("learning_evidence", {})
    
    if not evidence.get("targets"):
        return NodeResult.failure("缺少学习数据，无法生成计划")
    
    logger.info("前置条件校验通过", run_id=context.run_id)
    return NodeResult.success({"gate_passed": True}, next_node="propose_plan_delta")


async def _propose_plan_delta_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """生成计划变更草案"""
    evidence = context.get("learning_evidence", {})
    
    targets = evidence.get("targets", [])
    period = evidence.get("period") or "7天"
    preferred_daily_minutes = (evidence.get("preferences") or {}).get(
        "daily_study_minutes"
    )
    if (
        not isinstance(preferred_daily_minutes, int)
        or isinstance(preferred_daily_minutes, bool)
        or not 1 <= preferred_daily_minutes <= 1440
    ):
        preferred_daily_minutes = 30
    plan_draft = {
        "title": f"{context.user_id} 的学习计划",
        "period": period,
        "goals": [
            {
                "subject": target["title"],
                "target": target["target"],
                "daily_minutes": target.get("daily_minutes") or preferred_daily_minutes,
                "source": target["source"],
                "source_id": target.get("source_id"),
            }
            for target in targets[:3]
        ],
        "schedule": [
            {"day": i + 1, "focus": targets[i % len(targets)]["title"]}
            for i in range(7)
        ],
    }
    
    context.set("plan_draft", plan_draft)
    logger.info("计划草案生成", run_id=context.run_id, goals=len(plan_draft["goals"]))
    return NodeResult.success({"draft_created": True}, next_node="plan_quality_gate")


async def _plan_quality_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """计划质量校验"""
    plan_draft = context.get("plan_draft", {})
    
    # 简化为非空校验
    if not plan_draft.get("goals"):
        return NodeResult.failure("计划草案缺少目标")
    
    if len(plan_draft.get("goals", [])) == 0:
        return NodeResult.failure("计划目标为空")
    
    logger.info("计划质量校验通过", run_id=context.run_id)
    return NodeResult.success({"gate_passed": True}, next_node="create_approval")


async def _create_approval_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """创建审批请求"""
    from ..service import AgentService
    
    plan_draft = context.get("plan_draft", {})
    
    # 构建结构化的 diff 内容
    weak_areas = plan_draft.get("goals", [])
    schedule = plan_draft.get("schedule", [])
    
    diff_content = {
        "action_key": "plan_approval",
        "title": plan_draft.get("title", "学习计划"),
        "before": {
            "label": "当前计划",
            "items": [
                {"label": "学习周期", "value": "未设置"},
                {"label": "薄弱科目", "value": "未设定"},
                {"label": "每日目标", "value": "未设定"},
            ]
        },
        "after": {
            "label": "建议计划",
            "items": [
                {"label": "学习周期", "value": plan_draft.get("period", "7天")},
                {"label": "薄弱科目", "value": ", ".join([g.get("subject", "") for g in weak_areas]) if weak_areas else "未设定"},
                {"label": "每日目标", "value": f"{sum(g.get('daily_minutes', 0) for g in weak_areas)} 分钟" if weak_areas else "未设定"},
            ]
        },
        "summary": f"新增 {len(weak_areas)} 个学习目标，周期 {plan_draft.get('period', '7天')}",
        "details": [
            {"day": s.get("day"), "focus": s.get("focus", "")}
            for s in schedule
        ]
    }
    
    # 通过 AgentService 创建真实的审批记录
    service = AgentService(db)
    approval = await service.create_approval(
        run_id=context.run_id,
        action_key="plan_approval",
        diff_ref=_json.dumps(diff_content, ensure_ascii=False),
        expires_at=utc_now() + timedelta(hours=24),
    )
    
    context.set("approval_data", {
        "id": approval.id,
        "action_key": approval.action_key,
        "status": approval.status,
        "diff_ref": approval.diff_ref,
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
    })
    logger.info("审批请求创建", run_id=context.run_id, approval_id=approval.id)
    return NodeResult.success({"approval_created": True}, next_node="wait_for_approval")


async def _wait_for_approval_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """等待用户审批"""
    # 返回 WAITING 状态，引擎会保存断点并停止执行
    logger.info("等待用户审批", run_id=context.run_id)
    return NodeResult.waiting(next_node="apply_plan_change", output={"waiting_for_approval": True})


async def _apply_plan_change_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """应用计划变更"""
    from ..service import AgentService

    approval_id = (context.get("approval_data") or {}).get("id")
    approval = (
        await AgentService(db).get_approval(context.run_id, approval_id)
        if approval_id
        else None
    )
    if approval is None or approval.status != "approved":
        logger.warning(
            "计划变更未获批准",
            run_id=context.run_id,
            approval_id=approval_id,
            approval_status=approval.status if approval else None,
        )
        return NodeResult.failure("计划变更未获用户批准")

    plan_draft = context.get("plan_draft", {})
    
    # P1 简化：将计划保存到上下文中
    context.set("final_plan", plan_draft)
    logger.info("计划变更已应用", run_id=context.run_id)
    return NodeResult.success({"plan_applied": True}, next_node="render_plan_result")


async def _render_plan_result_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """渲染计划产物"""
    final_plan = context.get("final_plan", {})
    approval_id = (context.get("approval_data") or {}).get("id")
    
    artifact = {
        "type": "plan",
        "approval_id": approval_id,
        "title": final_plan.get("title", "学习计划"),
        "content": {
            "period": final_plan.get("period", "7天"),
            "goals": final_plan.get("goals", []),
            "schedule": final_plan.get("schedule", []),
        },
        "summary": f"包含 {len(final_plan.get('goals', []))} 个目标",
    }
    
    logger.info("计划产物渲染完成", run_id=context.run_id)
    return NodeResult(
        status=NodeStatus.COMPLETED,
        output={"artifact": artifact},
        next_node="completed",
        artifact=artifact,
    )


async def _completed_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """完成节点"""
    return NodeResult.success({"completed": True})


def build_plan_workflow() -> WorkflowDefinition:
    """构建 plan@v1 工作流"""
    wf = WorkflowDefinition(
        name="plan",
        version="v1",
        entry_node="aggregate_learning_evidence",
        max_model_calls=3,
    )
    
    wf.add_node(Node(name="aggregate_learning_evidence", node_type="action", execute=_aggregate_learning_evidence_node, description="聚合学习证据"))
    wf.add_node(Node(name="planning_precondition_gate", node_type="gate", execute=_planning_precondition_gate_node, description="前置条件"))
    wf.add_node(Node(name="propose_plan_delta", node_type="action", execute=_propose_plan_delta_node, description="生成计划草案"))
    wf.add_node(Node(name="plan_quality_gate", node_type="gate", execute=_plan_quality_gate_node, description="质量校验"))
    wf.add_node(Node(name="create_approval", node_type="action", execute=_create_approval_node, description="创建审批"))
    wf.add_node(Node(name="wait_for_approval", node_type="wait", execute=_wait_for_approval_node, description="等待审批"))
    wf.add_node(Node(name="apply_plan_change", node_type="action", execute=_apply_plan_change_node, description="应用变更"))
    wf.add_node(Node(name="render_plan_result", node_type="render", execute=_render_plan_result_node, description="渲染产物"))
    wf.add_node(Node(name="completed", node_type="render", execute=_completed_node, description="完成"))
    
    wf.add_edge("aggregate_learning_evidence", ["planning_precondition_gate"])
    wf.add_edge("planning_precondition_gate", ["propose_plan_delta"])
    wf.add_edge("propose_plan_delta", ["plan_quality_gate"])
    wf.add_edge("plan_quality_gate", ["create_approval"])
    wf.add_edge("create_approval", ["wait_for_approval"])
    wf.add_edge("wait_for_approval", ["apply_plan_change"])
    wf.add_edge("apply_plan_change", ["render_plan_result"])
    wf.add_edge("render_plan_result", ["completed"])
    
    return wf


# 注册
workflow_registry.register(build_plan_workflow())
