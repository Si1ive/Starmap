"""
validate@v1 工作流（用题验证）

load_learning_evidence -> question_discovery_loop -> question_gate ->
set_composition_gate -> practice.create_draft -> render_practice_artifact -> completed
"""

from typing import Dict, Any, Optional, List
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, Node, NodeResult, ExecutionContext
from .registry import workflow_registry
from ..model_runtime.adapter import model_adapter
from ..model_runtime.policy_gate import policy_gate

logger = get_logger(__name__)


async def _load_learning_evidence_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """读取用户学习证据"""
    user_id = context.user_id
    # 简化为从上下文获取，实际应从 learning 模块查询
    evidence = {
        "mastery_levels": {},
        "recent_topics": [],
        "weak_areas": [],
    }
    context.set("learning_evidence", evidence)
    logger.info("学习证据加载", run_id=context.run_id, user_id=user_id)
    return NodeResult.success({"evidence": evidence}, next_node="question_discovery_loop")


async def _question_discovery_loop_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """检索候选题目"""
    from ..tools.retrieve_knowledge import retrieve_knowledge
    
    input_msg = context.get("input_message", "")
    
    # 检索相关题目
    candidates = await retrieve_knowledge(
        db,
        query=input_msg,
        limit=10,
        filters={"type": "question"}
    )
    
    context.set("question_candidates", candidates)
    logger.info("候选题目发现", run_id=context.run_id, count=len(candidates.get("results", [])))
    return NodeResult.success({"candidate_count": len(candidates.get("results", []))}, next_node="question_gate")


async def _question_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """题目资格校验"""
    candidates = context.get("question_candidates", {})
    results = candidates.get("results", [])
    
    # P1 简化：过滤掉明显不符合要求的
    valid_questions = []
    for q in results:
        # 基础校验：有题干、有答案
        if q.get("question_text") and q.get("answer"):
            valid_questions.append(q)
    
    if len(valid_questions) < 3:
        logger.warning("候选题目不足", run_id=context.run_id, count=len(valid_questions))
        return NodeResult.success(
            {"gate_passed": False, "reason": "候选题目不足"},
            next_node="render_practice_artifact"  # 降级继续
        )
    
    context.set("valid_questions", valid_questions)
    logger.info("题目校验通过", run_id=context.run_id, count=len(valid_questions))
    return NodeResult.success({"gate_passed": True, "count": len(valid_questions)}, next_node="composition_gate")


async def _composition_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """题目组合校验"""
    valid_questions = context.get("valid_questions", [])
    
    # P1 简化：选择前5题作为练习集
    selected = valid_questions[:5]
    context.set("selected_questions", selected)
    
    logger.info("题目组合完成", run_id=context.run_id, count=len(selected))
    return NodeResult.success({"composition_passed": True, "count": len(selected)}, next_node="create_practice_draft")


async def _create_practice_draft_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """创建练习草稿（唯一副作用）"""
    selected = context.get("selected_questions", [])
    
    # 创建练习草稿
    practice_draft = {
        "session_id": f"ps_{context.run_id}",
        "questions": [
            {
                "id": q.get("id"),
                "type": q.get("type", "single_choice"),
                "text": q.get("question_text"),
                "options": q.get("options", []),
                "difficulty": q.get("difficulty", "medium"),
                "subject": q.get("subject", "unknown"),
            }
            for q in selected
        ],
        "total_questions": len(selected),
        "time_limit": len(selected) * 2,  # 每题2分钟
        "mode": "validation",
    }
    
    context.set("practice_draft", practice_draft)
    logger.info("练习草稿创建", run_id=context.run_id, question_count=len(selected))
    return NodeResult.success({"draft_created": True}, next_node="render_practice_artifact")


async def _render_practice_artifact_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """渲染练习产物"""
    practice_draft = context.get("practice_draft", {})
    
    artifact = {
        "type": "practice",
        "title": "用题验证练习",
        "content": practice_draft,
        "summary": f"共 {practice_draft.get('total_questions', 0)} 道题目",
    }
    
    logger.info("练习产物渲染完成", run_id=context.run_id)
    return NodeResult.success({"artifact": artifact}, next_node="completed")


async def _completed_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """完成节点"""
    return NodeResult.success({"completed": True})


def build_validate_workflow() -> WorkflowDefinition:
    """构建 validate@v1 工作流"""
    wf = WorkflowDefinition(
        name="validate",
        version="v1",
        entry_node="load_learning_evidence",
        max_model_calls=4,
    )
    
    wf.add_node(Node(name="load_learning_evidence", node_type="action", execute=_load_learning_evidence_node, description="加载学习证据"))
    wf.add_node(Node(name="question_discovery_loop", node_type="loop", execute=_question_discovery_loop_node, description="题目发现"))
    wf.add_node(Node(name="question_gate", node_type="gate", execute=_question_gate_node, description="题目校验"))
    wf.add_node(Node(name="composition_gate", node_type="gate", execute=_composition_gate_node, description="组合校验"))
    wf.add_node(Node(name="create_practice_draft", node_type="action", execute=_create_practice_draft_node, description="创建练习"))
    wf.add_node(Node(name="render_practice_artifact", node_type="render", execute=_render_practice_artifact_node, description="渲染产物"))
    wf.add_node(Node(name="completed", node_type="render", execute=_completed_node, description="完成"))
    
    wf.add_edge("load_learning_evidence", ["question_discovery_loop"])
    wf.add_edge("question_discovery_loop", ["question_gate"])
    wf.add_edge("question_gate", ["composition_gate"])
    wf.add_edge("composition_gate", ["create_practice_draft"])
    wf.add_edge("create_practice_draft", ["render_practice_artifact"])
    wf.add_edge("render_practice_artifact", ["completed"])
    
    return wf


# 注册
workflow_registry.register(build_validate_workflow())
