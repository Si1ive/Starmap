"""
grade@v1 工作流（批改反馈）

load_attempt_snapshot -> objective_grade -> rubric_gate ->
generate_feedback -> feedback_gate -> render_artifact -> completed
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, Node, NodeResult, ExecutionContext
from .registry import workflow_registry
from ..memory_selector import load_evaluation_bundle

logger = get_logger(__name__)

_OBJECTIVE_QUESTION_TYPES = {"choice", "fill", "judge"}
_CHOICE_TOKEN_PATTERN = re.compile(r"(?:选(?:择)?\s*)?([A-H])\b", re.IGNORECASE)
_JUDGE_TRUE = {"正确", "对", "√", "true", "是"}
_JUDGE_FALSE = {"错误", "不正确", "不对", "错", "×", "false", "否"}


def _normalize_answer(answer: str, question_type: str) -> str:
    normalized = str(answer or "").strip()
    if question_type == "choice":
        match = _CHOICE_TOKEN_PATTERN.search(normalized)
        return match.group(1).upper() if match else normalized.casefold()
    if question_type == "judge":
        folded = normalized.casefold()
        if folded in {item.casefold() for item in _JUDGE_TRUE}:
            return "true"
        if folded in {item.casefold() for item in _JUDGE_FALSE}:
            return "false"
        return folded
    return "".join(normalized.split()).casefold()


async def _load_attempt_snapshot_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """读取固化题面和作答"""
    bundle = await load_evaluation_bundle(
        db,
        run_id=context.run_id,
        user_id=context.user_id,
    )
    if bundle.question is None or bundle.user_answer is None:
        reason_messages = {
            "run_not_found": "评分运行不存在",
            "snapshot_not_found": "缺少本轮记忆快照，无法安全评分",
            "question_reference_missing": "缺少明确的题目引用，无法评分",
            "question_reference_ambiguous": "本轮引用了多道题，请明确要批改的题目",
            "question_not_eligible": "题目不存在、已失效或缺少可信标准答案",
            "user_answer_missing": "没有识别到明确作答，请使用“我的答案是……”提交",
        }
        return NodeResult.failure(
            reason_messages.get(bundle.unresolved_reason, "缺少可信评分数据")
        )

    question = bundle.question
    attempt = {
        "user_id": context.user_id,
        "question_id": question.id,
        "question_type": question.question_type,
        "question_content": question.content,
        "options": question.options,
        "standard_answer": question.standard_answer,
        "answer_source": question.answer_source,
        "explanation": question.explanation,
        "knowledge_point_ids": question.knowledge_point_ids,
        "subject_id": question.subject_id,
        "source_artifact_id": question.source_artifact_id,
        "user_answer": bundle.user_answer,
    }
    context.set("evaluation_bundle", bundle.model_dump(mode="json"))
    context.set("attempt", attempt)
    logger.info("作答加载", run_id=context.run_id, question_id=attempt["question_id"])
    return NodeResult.success({"snapshot_loaded": True}, next_node="objective_grade")


async def _objective_grade_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """客观题确定性判定"""
    attempt = context.get("attempt", {})
    question_type = attempt.get("question_type")
    if question_type not in _OBJECTIVE_QUESTION_TYPES:
        return NodeResult.failure("当前仅支持选择题、填空题和判断题的确定性批改")

    normalized_user_answer = _normalize_answer(
        attempt.get("user_answer", ""),
        question_type,
    )
    normalized_standard_answer = _normalize_answer(
        attempt.get("standard_answer", ""),
        question_type,
    )
    if not normalized_user_answer or not normalized_standard_answer:
        return NodeResult.failure("作答或标准答案无法确定性归一化")

    is_correct = normalized_user_answer == normalized_standard_answer
    verdict = "correct" if is_correct else "incorrect"
    objective_result = {
        "question_id": attempt["question_id"],
        "question_type": question_type,
        "is_objective": True,
        "user_answer": attempt["user_answer"],
        "standard_answer": attempt["standard_answer"],
        "answer_source": attempt["answer_source"],
        "verdict": verdict,
        "score": 1.0 if is_correct else 0.0,
    }
    grading_evidence = {
        "verdict": verdict,
        "question_id": attempt["question_id"],
        "knowledge_point_ids": attempt.get("knowledge_point_ids") or [],
        "subject_id": attempt.get("subject_id"),
        "evidence_id": context.run_id,
        "score": objective_result["score"],
        "error_types": [] if is_correct else ["answer_mismatch"],
        "answer_source": attempt["answer_source"],
    }
    context.set("objective_result", objective_result)
    context.set("grading_evidence", grading_evidence)
    logger.info(
        "客观题判定",
        run_id=context.run_id,
        question_id=attempt["question_id"],
        verdict=verdict,
    )
    return NodeResult.success({"graded": True}, next_node="rubric_gate")


async def _rubric_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """rubric 校验"""
    objective_result = context.get("objective_result", {})
    
    rubric = {
        "completeness": len(objective_result.get("user_answer", "")) > 0,
        "deterministic": objective_result.get("is_objective") is True,
        "trusted_answer": objective_result.get("answer_source")
        in {"extracted", "manual", "llm"},
    }
    if not all(rubric.values()):
        return NodeResult.failure("评分证据门禁未通过")

    context.set("rubric", rubric)
    logger.info("rubric 校验", run_id=context.run_id, **rubric)
    return NodeResult.success({"gate_passed": True}, next_node="generate_feedback")


async def _generate_feedback_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """根据确定性判定生成有证据的反馈"""
    attempt = context.get("attempt", {})
    result = context.get("objective_result", {})
    is_correct = result.get("verdict") == "correct"
    feedback = (
        {
            "overall": "回答正确",
            "strengths": ["作答与可信标准答案一致"],
            "weaknesses": [],
            "suggestions": ["可以继续练习同类题目巩固掌握度"],
        }
        if is_correct
        else {
            "overall": "回答错误",
            "strengths": ["已提交可确定性判定的明确答案"],
            "weaknesses": [
                f"你的答案是 {attempt.get('user_answer')}，标准答案是 {attempt.get('standard_answer')}"
            ],
            "suggestions": [
                attempt.get("explanation") or "请结合标准答案复盘错误原因"
            ],
        }
    )
    context.set("feedback", feedback)
    logger.info("反馈生成", run_id=context.run_id, feedback_summary=feedback["overall"])
    return NodeResult.success({"feedback_generated": True}, next_node="feedback_gate")


async def _feedback_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """反馈证据校验"""
    feedback = context.get("feedback", {})
    
    if not feedback.get("overall"):
        logger.warning("反馈为空", run_id=context.run_id)
        return NodeResult.failure("反馈生成失败")
    
    logger.info("反馈校验通过", run_id=context.run_id)
    return NodeResult.success({"gate_passed": True}, next_node="render_artifact")


async def _render_artifact_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """渲染反馈产物"""
    feedback = context.get("feedback", {})

    content = {
        "overall": feedback.get("overall", ""),
        "strengths": feedback.get("strengths", []),
        "weaknesses": feedback.get("weaknesses", []),
        "suggestions": feedback.get("suggestions", []),
    }
    # 只有确定性判定产生真实 verdict 时才携带结构化评分证据。
    grading_evidence = context.get("grading_evidence") or {}
    if grading_evidence.get("verdict"):
        content["grading"] = grading_evidence

    artifact = {
        "type": "feedback",
        "title": "批改反馈",
        "content": content,
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
