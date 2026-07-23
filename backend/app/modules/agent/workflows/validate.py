"""
validate@v1 工作流（用题验证）

load_learning_evidence -> question_discovery_loop -> question_gate ->
set_composition_gate -> practice.create_draft -> render_practice_artifact -> completed
"""

from datetime import datetime
from typing import Dict, Any, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, Node, NodeResult, ExecutionContext
from .registry import workflow_registry

logger = get_logger(__name__)


async def _load_learning_evidence_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """读取用户学习证据"""
    # P1 简化：从上下文获取
    evidence = {
        "user_id": context.user_id,
        "weak_areas": context.get("weak_areas", ["数据结构", "操作系统"]),
        "strong_areas": context.get("strong_areas", ["计算机网络"]),
        "recent_topics": context.get("recent_topics", []),
    }
    context.set("learning_evidence", evidence)
    logger.info("学习证据加载", run_id=context.run_id, weak_areas=evidence["weak_areas"])
    return NodeResult.success({"evidence_loaded": True}, next_node="question_discovery")


async def _question_discovery_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """检索候选题"""
    from ..tools.retrieve_knowledge import retrieve_knowledge
    
    evidence = context.get("learning_evidence", {})
    weak_areas = evidence.get("weak_areas", [])
    
    # 检索候选题目
    query = " ".join(weak_areas) if weak_areas else "数据结构 栈和队列"
    
    result = await retrieve_knowledge(
        db,
        query=query,
        entity_type="question",
        limit=10,
    )
    
    candidates = result.get("results", [])
    context.set("candidates", candidates)
    logger.info("候选题检索", run_id=context.run_id, count=len(candidates))
    return NodeResult.success({"questions_found": len(candidates)}, next_node="question_gate")


async def _question_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """题目资格校验"""
    candidates = context.get("candidates", [])
    
    # P1 简化：过滤掉不符合条件的题目
    valid = []
    for q in candidates:
        # 检查题目质量
        if q.get("source_type") in ["exam", "textbook", "practice"]:
            valid.append(q)
    
    # 如果没有有效题目，返回降级
    if not valid:
        logger.warning("无有效候选题", run_id=context.run_id)
        return NodeResult.failure("未找到有效候选题")
    
    context.set("valid_questions", valid[:5])  # 最多取5道
    logger.info("题目校验通过", run_id=context.run_id, valid_count=len(valid))
    return NodeResult.success({"gate_passed": True}, next_node="composition_gate")


async def _composition_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """题目组合校验"""
    valid_questions = context.get("valid_questions", [])
    
    # P1 简化：检查题目组合是否均衡
    # 实际项目中应根据题型、难度、考点等维度进行组合校验
    composition = {
        "total": len(valid_questions),
        "types": {},
        "difficulties": {},
        "subjects": {},
    }
    
    for q in valid_questions:
        q_type = q.get("type", "unknown")
        difficulty = q.get("difficulty", "unknown")
        subject = q.get("subject", "unknown")
        composition["types"][q_type] = composition["types"].get(q_type, 0) + 1
        composition["difficulties"][difficulty] = composition["difficulties"].get(difficulty, 0) + 1
        composition["subjects"][subject] = composition["subjects"].get(subject, 0) + 1
    
    context.set("composition", composition)
    logger.info("组合校验", run_id=context.run_id, **composition)
    return NodeResult.success({"gate_passed": True}, next_node="create_draft")


async def _create_draft_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """创建练习草稿（唯一副作用）"""
    valid_questions = context.get("valid_questions", [])
    composition = context.get("composition", {})
    
    draft = {
        "title": f"专项练习 · {context.user_id}",
        "questions": valid_questions,
        "composition": composition,
        "created_at": str(datetime.utcnow()),
    }
    
    context.set("practice_draft", draft)
    logger.info("练习草稿创建", run_id=context.run_id, question_count=len(valid_questions))
    return NodeResult.success({"draft_created": True}, next_node="render_artifact")


async def _render_artifact_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """渲染练习产物"""
    draft = context.get("practice_draft", {})
    composition = context.get("composition", {})
    
    artifact = {
        "type": "practice",
        "title": draft.get("title", "专项练习"),
        "content": {
            "question_count": len(draft.get("questions", [])),
            "composition": composition,
        },
        "summary": f"共 {len(draft.get('questions', []))} 道题，覆盖 {len(composition.get('subjects', {}))} 个考点",
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


def build_validate_workflow() -> WorkflowDefinition:
    """构建 validate@v1 工作流"""
    wf = WorkflowDefinition(
        name="validate",
        version="v1",
        entry_node="load_learning_evidence",
        max_model_calls=3,
    )
    
    wf.add_node(Node(name="load_learning_evidence", node_type="action", execute=_load_learning_evidence_node, description="加载学习证据"))
    wf.add_node(Node(name="question_discovery", node_type="loop", execute=_question_discovery_node, description="检索候选题"))
    wf.add_node(Node(name="question_gate", node_type="gate", execute=_question_gate_node, description="题目校验"))
    wf.add_node(Node(name="composition_gate", node_type="gate", execute=_composition_gate_node, description="组合校验"))
    wf.add_node(Node(name="create_draft", node_type="action", execute=_create_draft_node, description="创建草稿"))
    wf.add_node(Node(name="render_artifact", node_type="render", execute=_render_artifact_node, description="渲染产物"))
    wf.add_node(Node(name="completed", node_type="render", execute=_completed_node, description="完成"))
    
    wf.add_edge("load_learning_evidence", ["question_discovery"])
    wf.add_edge("question_discovery", ["question_gate"])
    wf.add_edge("question_gate", ["composition_gate"])
    wf.add_edge("composition_gate", ["create_draft"])
    wf.add_edge("create_draft", ["render_artifact"])
    wf.add_edge("render_artifact", ["completed"])
    
    return wf


# 注册
workflow_registry.register(build_validate_workflow())
