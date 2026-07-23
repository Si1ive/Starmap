"""
grade@v1 工作流（批改反馈）

load_attempt_snapshot -> objective_grade_or_skip -> resolve_rubric_gate ->
generate_subjective_feedback -> feedback_support_gate -> create_feedback_artifact -> completed
"""

from typing import Dict, Any, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, Node, NodeResult, ExecutionContext
from .registry import workflow_registry
from ..time_utils import utc_isoformat, utc_now

logger = get_logger(__name__)


async def _load_attempt_snapshot_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """读取固化题面和作答"""
    # 从上下文获取作答数据
    attempt = {
        "user_id": context.user_id,
        "question_id": context.get("question_id", "unknown"),
        "user_answer": context.get("user_answer", ""),
        "submitted_at": utc_isoformat(utc_now()),
    }
    context.set("attempt", attempt)
    logger.info("作答加载", run_id=context.run_id, question_id=attempt["question_id"])
    return NodeResult.success({"snapshot_loaded": True}, next_node="objective_grade")


async def _objective_grade_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """客观题确定性判定"""
    attempt = context.get("attempt", {})
    user_answer = attempt.get("user_answer", "")
    
    # P1 简化：客观题判定
    # 实际项目中应调用评分服务
    # 这里简单模拟：如果答案不为空，标记为需要人工复核
    objective_result = {
        "question_id": attempt.get("question_id", "unknown"),
        "is_objective": False,  # P1 简化：全部走主观反馈
        "user_answer": user_answer,
        "submitted_at": attempt.get("submitted_at", ""),
    }
    
    context.set("objective_result", objective_result)
    logger.info("客观题判定", run_id=context.run_id, is_objective=False)
    return NodeResult.success({"graded": True}, next_node="rubric_gate")


async def _rubric_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """rubric 校验"""
    objective_result = context.get("objective_result", {})
    
    # P1 简化：rubric 校验
    rubric = {
        "completeness": len(objective_result.get("user_answer", "")) > 0,
        "relevance": True,
        "format": True,
    }
    
    context.set("rubric", rubric)
    logger.info("rubric 校验", run_id=context.run_id, **rubric)
    return NodeResult.success({"gate_passed": True}, next_node="generate_feedback")


async def _generate_feedback_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """生成主观反馈"""
    attempt = context.get("attempt", {})
    rubric = context.get("rubric", {})
    
    # P1 简化：生成反馈
    feedback = {
        "overall": "作答已收到，正在分析...",
        "strengths": [
            "答题完整度良好" if rubric.get("completeness") else "需要补充更多内容",
        ],
        "weaknesses": [
            "部分细节可以进一步完善",
        ],
        "suggestions": [
            "建议回顾相关知识点",
            "多做同类题型巩固",
        ],
    }
    
    context.set("feedback", feedback)
    logger.info("反馈生成", run_id=context.run_id, feedback_summary=feedback["overall"])
    return NodeResult.success({"feedback_generated": True}, next_node="feedback_gate")


async def _feedback_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """反馈证据校验"""
    feedback = context.get("feedback", {})
    
    # P1 简化：检查反馈是否有内容
    if not feedback.get("overall"):
        logger.warning("反馈为空", run_id=context.run_id)
        return NodeResult.failure("反馈生成失败")
    
    logger.info("反馈校验通过", run_id=context.run_id)
    return NodeResult.success({"gate_passed": True}, next_node="render_artifact")


async def _render_artifact_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """渲染反馈产物"""
    feedback = context.get("feedback", {})
    attempt = context.get("attempt", {})
    
    artifact = {
        "type": "feedback",
        "title": "批改反馈",
        "content": {
            "overall": feedback.get("overall", ""),
            "strengths": feedback.get("strengths", []),
            "weaknesses": feedback.get("weaknesses", []),
            "suggestions": feedback.get("suggestions", []),
        },
        "summary": feedback.get("overall", "反馈已生成"),
    }
    
    logger.info("产物渲染完成", run_id=context.run_id)
    return NodeResult.success(
        {"artifact": artifact},
        next_node="completed",
        artifact=artifact,
    )


async def _completed_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """完成节点"""
    return NodeResult.success({"completed": True})


def build_grade_workflow() -> WorkflowDefinition:
    """构建 grade@v1 工作流"""
    wf = WorkflowDefinition(
        name="grade",
        version="v1",
        entry_node="load_attempt_snapshot",
        max_model_calls=2,
    )
    
    wf.add_node(Node(name="load_attempt_snapshot", node_type="action", execute=_load_attempt_snapshot_node, description="加载作答"))
    wf.add_node(Node(name="objective_grade", node_type="gate", execute=_objective_grade_node, description="客观题判定"))
    wf.add_node(Node(name="rubric_gate", node_type="gate", execute=_rubric_gate_node, description="rubric校验"))
    wf.add_node(Node(name="generate_feedback", node_type="action", execute=_generate_feedback_node, description="生成反馈"))
    wf.add_node(Node(name="feedback_gate", node_type="gate", execute=_feedback_gate_node, description="反馈校验"))
    wf.add_node(Node(name="render_artifact", node_type="render", execute=_render_artifact_node, description="渲染产物"))
    wf.add_node(Node(name="completed", node_type="render", execute=_completed_node, description="完成"))
    
    wf.add_edge("load_attempt_snapshot", ["objective_grade"])
    wf.add_edge("objective_grade", ["rubric_gate"])
    wf.add_edge("rubric_gate", ["generate_feedback"])
    wf.add_edge("generate_feedback", ["feedback_gate"])
    wf.add_edge("feedback_gate", ["render_artifact"])
    wf.add_edge("render_artifact", ["completed"])
    
    return wf


# 注册
workflow_registry.register(build_grade_workflow())
