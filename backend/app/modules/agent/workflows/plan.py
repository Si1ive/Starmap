"""
plan@v1 工作流（学习计划，简化版）

aggregate_learning_evidence -> planning_precondition_gate -> propose_plan_delta ->
plan_quality_gate -> create_approval -> wait_for_approval -> apply_plan_change -> render_plan_result -> completed
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, Node, NodeResult, ExecutionContext
from .registry import workflow_registry
from ..model_runtime.adapter import model_adapter
from ..state_machine import RunStatus, state_machine

logger = get_logger(__name__)


async def _aggregate_learning_evidence_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """聚合学习证据"""
    user_id = context.user_id
    
    # 简化的学习证据聚合
    evidence = {
        "user_id": user_id,
        "total_practice_sessions": 0,
        "average_score": 0.0,
        "weak_areas": ["数据结构", "操作系统"],
        "strong_areas": ["计算机网络"],
        "study_streak": 0,
        "daily_goal_minutes": 60,
    }
    
    context.set("learning_evidence", evidence)
    logger.info("学习证据聚合", run_id=context.run_id, user_id=user_id)
    return NodeResult.success({"evidence_aggregated": True}, next_node="planning_precondition_gate")


async def _planning_precondition_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """前置条件校验"""
    evidence = context.get("learning_evidence", {})
    
    # 检查是否有足够的数据
    if not evidence.get("weak_areas"):
        return NodeResult.failure("缺少学习数据，无法生成计划")
    
    logger.info("前置条件校验通过", run_id=context.run_id)
    return NodeResult.success({"gate_passed": True}, next_node="propose_plan_delta")


async def _propose_plan_delta_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """生成计划变更草案"""
    evidence = context.get("learning_evidence", {})
    
    # P1 简化：使用可配置规则模板
    weak_areas = evidence.get("weak_areas", [])
    
    # 生成计划草案
    plan_draft = {
        "title": f"{context.user_id} 的学习计划",
        "period": "7天",
        "goals": [
            {
                "subject": area,
                "target": "掌握基础概念",
                "daily_minutes": 30,
            }
            for area in weak_areas[:3]  # 最多3个薄弱点
        ],
        "schedule": [
            {"day": i + 1, "focus": weak_areas[i % len(weak_areas)] if weak_areas else "复习"}
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
    
    # 通过 AgentService 创建真实的审批记录
    service = AgentService(db)
    approval = await service.create_approval(
        run_id=context.run_id,
        action_key="plan_approval",
        diff_ref=str(plan_draft),
        expires_at=datetime.utcnow() + timedelta(hours=24),
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
    plan_draft = context.get("plan_draft", {})
    
    # P1 简化：将计划保存到上下文中
    context.set("final_plan", plan_draft)
    logger.info("计划变更已应用", run_id=context.run_id)
    return NodeResult.success({"plan_applied": True}, next_node="render_plan_result")


async def _render_plan_result_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """渲染计划产物"""
    final_plan = context.get("final_plan", {})
    
    artifact = {
        "type": "plan",
        "title": final_plan.get("title", "学习计划"),
        "content": {
            "period": final_plan.get("period", "7天"),
            "goals": final_plan.get("goals", []),
            "schedule": final_plan.get("schedule", []),
        },
        "summary": f"包含 {len(final_plan.get('goals', []))} 个目标",
    }
    
    logger.info("计划产物渲染完成", run_id=context.run_id)
    return NodeResult.success({"artifact": artifact}, next_node="completed")


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
