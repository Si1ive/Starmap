"""
grade@v1 工作流（批改反馈）

load_attempt_snapshot -> objective_grade_or_skip -> resolve_rubric_gate ->
generate_subjective_feedback -> feedback_support_gate -> create_feedback_artifact -> completed
"""

from typing import Dict, Any, Optional, List
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, Node, NodeResult, ExecutionContext
from .registry import workflow_registry
from ..model_runtime.adapter import model_adapter

logger = get_logger(__name__)


async def _load_attempt_snapshot_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """读取固化题面和作答"""
    # 从上下文获取作答信息
    attempt = context.get("attempt_data", {})
    snapshot = {
        "question_id": attempt.get("question_id"),
        "question_text": attempt.get("question_text"),
        "user_answer": attempt.get("user_answer"),
        "correct_answer": attempt.get("correct_answer"),
        "subject": attempt.get("subject"),
        "difficulty": attempt.get("difficulty"),
    }
    context.set("attempt_snapshot", snapshot)
    logger.info("作答快照加载", run_id=context.run_id, question_id=snapshot.get("question_id"))
    return NodeResult.success({"loaded": True}, next_node="objective_grade_or_skip")


async def _objective_grade_or_skip_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """客观题确定性判定"""
    snapshot = context.get("attempt_snapshot", {})
    
    user_answer = snapshot.get("user_answer", "").strip().upper()
    correct_answer = snapshot.get("correct_answer", "").strip().upper()
    
    # 客观题判定：选项匹配
    is_correct = user_answer == correct_answer
    
    grade_result = {
        "question_id": snapshot.get("question_id"),
        "is_correct": is_correct,
        "user_answer": user_answer,
        "correct_answer": correct_answer,
        "objective": True,
        "score": 1.0 if is_correct else 0.0,
    }
    
    context.set("grade_result", grade_result)
    logger.info("客观判定完成", run_id=context.run_id, is_correct=is_correct)
    return NodeResult.success({"graded": True, "is_correct": is_correct}, next_node="rubric_gate")


async def _rubric_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """Rubric 校验"""
    grade_result = context.get("grade_result", {})
    
    # 检查是否有必要数据
    if not grade_result.get("question_id"):
        return NodeResult.failure("缺少题目信息")
    
    logger.info("Rubric校验通过", run_id=context.run_id)
    return NodeResult.success({"gate_passed": True}, next_node="generate_subjective_feedback")


async def _generate_subjective_feedback_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """生成主观反馈"""
    snapshot = context.get("attempt_snapshot", {})
    grade_result = context.get("grade_result", {})
    
    is_correct = grade_result.get("is_correct", False)
    
    # P1 简化：根据正误生成简单反馈
    if is_correct:
        feedback = {
            "type": "praise",
            "message": "回答正确！继续保持。",
            "tips": ["这道题考查的是基础概念，建议复习相关章节"],
            "related_concepts": [snapshot.get("subject", "")],
        }
    else:
        feedback = {
            "type": "correction",
            "message": f"回答错误。正确答案是：{grade_result.get('correct_answer', 'N/A')}",
            "tips": ["请仔细审题，注意选项的细微差别"],
            "related_concepts": [snapshot.get("subject", "")],
        }
    
    context.set("subjective_feedback", feedback)
    logger.info("主观反馈生成", run_id=context.run_id, is_correct=is_correct)
    return NodeResult.success({"feedback_generated": True}, next_node="feedback_support_gate")


async def _feedback_support_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """反馈证据校验"""
    feedback = context.get("subjective_feedback", {})
    
    # 简化为非空校验
    if not feedback.get("message"):
        return NodeResult.failure("反馈内容为空")
    
    logger.info("反馈校验通过", run_id=context.run_id)
    return NodeResult.success({"gate_passed": True}, next_node="create_feedback_artifact")


async def _create_feedback_artifact_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """渲染反馈产物"""
    grade_result = context.get("grade_result", {})
    feedback = context.get("subjective_feedback", {})
    
    artifact = {
        "type": "feedback",
        "title": "批改反馈",
        "content": {
            "grade": grade_result,
            "feedback": feedback,
        },
        "summary": "批改完成",
    }
    
    logger.info("反馈产物渲染完成", run_id=context.run_id)
    return NodeResult.success({"artifact": artifact}, next_node="completed")


async def _completed_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """完成节点"""
    return NodeResult.success({"completed": True})


def build_grade_workflow() -> WorkflowDefinition:
    """构建 grade@v1 工作流"""
    wf = WorkflowDefinition(
        name="grade",
        version="v1",
        entry_node="load_attempt_snapshot",
        max_model_calls=3,
    )
    
    wf.add_node(Node(name="load_attempt_snapshot", node_type="action", execute=_load_attempt_snapshot_node, description="加载作答快照"))
    wf.add_node(Node(name="objective_grade_or_skip", node_type="gate", execute=_objective_grade_or_skip_node, description="客观判定"))
    wf.add_node(Node(name="rubric_gate", node_type="gate", execute=_rubric_gate_node, description="Rubric校验"))
    wf.add_node(Node(name="generate_subjective_feedback", node_type="action", execute=_generate_subjective_feedback_node, description="生成反馈"))
    wf.add_node(Node(name="feedback_support_gate", node_type="gate", execute=_feedback_support_gate_node, description="反馈校验"))
    wf.add_node(Node(name="create_feedback_artifact", node_type="render", execute=_create_feedback_artifact_node, description="渲染产物"))
    wf.add_node(Node(name="completed", node_type="render", execute=_completed_node, description="完成"))
    
    wf.add_edge("load_attempt_snapshot", ["objective_grade_or_skip"])
    wf.add_edge("objective_grade_or_skip", ["rubric_gate"])
    wf.add_edge("rubric_gate", ["generate_subjective_feedback"])
    wf.add_edge("generate_subjective_feedback", ["feedback_support_gate"])
    wf.add_edge("feedback_support_gate", ["create_feedback_artifact"])
    wf.add_edge("create_feedback_artifact", ["completed"])
    
    return wf


# 注册
workflow_registry.register(build_grade_workflow())
