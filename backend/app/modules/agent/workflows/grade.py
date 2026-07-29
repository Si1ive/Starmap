"""
grade@v1 工作流（批改反馈）

load_attempt_snapshot -> objective_grade/open_answer_assessment -> rubric_gate ->
generate_feedback -> feedback_gate -> render_artifact -> completed
"""

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, Node, NodeResult, ExecutionContext
from .registry import workflow_registry
from ..memory_selector import load_evaluation_bundle
from ..model_runtime.assessor import (
    OPEN_ANSWER_ASSESSOR_VERSION,
    OpenAnswerAssessment,
    OpenAnswerAssessorDeps,
    OpenAnswerRubric,
    normalize_open_answer_assessment,
    open_answer_assessor_runtime,
    stable_open_answer_evidence_id,
    weighted_criterion_score,
)
from ..model_runtime.teaching_policy import load_frozen_teaching_policy

logger = get_logger(__name__)

_OBJECTIVE_QUESTION_TYPES = {"choice", "fill", "judge"}
_OPEN_QUESTION_TYPES = {"short_answer", "design", "analysis"}
_CHOICE_TOKEN_PATTERN = re.compile(r"(?:选(?:择)?\s*)?([A-H])\b", re.IGNORECASE)
_JUDGE_TRUE = {"正确", "对", "√", "true", "是"}
_JUDGE_FALSE = {"错误", "不正确", "不对", "错", "×", "false", "否"}


def _build_open_answer_rubric(question: Any) -> dict[str, Any] | None:
    """从冻结标准答案和解析构造服务端 rubric；缺标准答案时不猜测。"""
    standard_answer = str(getattr(question, "standard_answer", "") or "").strip()
    if not standard_answer:
        return None
    criteria = [
        {
            "criterion_id": "core_concepts",
            "description": f"回答必须覆盖冻结标准答案中的核心要点：{standard_answer[:1800]}",
            "weight": 0.7 if getattr(question, "explanation", None) else 1.0,
        }
    ]
    explanation = str(getattr(question, "explanation", "") or "").strip()
    if explanation:
        criteria.append(
            {
                "criterion_id": "reasoning",
                "description": f"回答的推理或适用条件应与冻结解析一致：{explanation[:1800]}",
                "weight": 0.3,
            }
        )
    return OpenAnswerRubric(
        version="rubric-v1",
        criteria=criteria,
        source_answer_source=str(getattr(question, "answer_source", "unknown")),
    ).model_dump(mode="json")


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


async def _load_attempt_snapshot_node(
    context: ExecutionContext, db: AsyncSession
) -> NodeResult:
    """读取固化题面和作答"""
    teaching_policy = load_frozen_teaching_policy(
        context,
        workflow_action="grade",
    )
    context.set("teaching_policy", teaching_policy.model_dump(mode="json"))
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
        "hint_levels_used": list(bundle.hint_levels_used),
        "answer_exposed": bundle.answer_exposed,
        "model_version": question.model_version,
        "answer_confidence": question.answer_confidence,
        "rubric": (
            _build_open_answer_rubric(question)
            if question.question_type in _OPEN_QUESTION_TYPES
            else None
        ),
    }
    context.set("evaluation_bundle", bundle.model_dump(mode="json"))
    context.set("attempt", attempt)
    logger.info("作答加载", run_id=context.run_id, question_id=attempt["question_id"])
    if question.question_type in _OBJECTIVE_QUESTION_TYPES:
        next_node = "objective_grade"
    elif question.question_type in _OPEN_QUESTION_TYPES:
        next_node = "open_answer_assessment"
    else:
        return NodeResult.failure("当前题型不支持安全批改")
    return NodeResult.success({"snapshot_loaded": True}, next_node=next_node)


async def _objective_grade_node(
    context: ExecutionContext, db: AsyncSession
) -> NodeResult:
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
    if attempt.get("model_version") or attempt.get("answer_confidence") is not None:
        grading_evidence.update(
            {
                "assessment_source": "generated_question",
                "model_version": attempt.get("model_version"),
                "answer_confidence": attempt.get("answer_confidence"),
            }
        )
    context.set("objective_result", objective_result)
    context.set("grading_evidence", grading_evidence)
    logger.info(
        "客观题判定",
        run_id=context.run_id,
        question_id=attempt["question_id"],
        verdict=verdict,
    )
    return NodeResult.success({"graded": True}, next_node="rubric_gate")


def _open_answer_grading_evidence(
    context: ExecutionContext,
    attempt: dict[str, Any],
    assessment: OpenAnswerAssessment,
    rubric: OpenAnswerRubric | None,
) -> dict[str, Any]:
    """把 Assessor 结果转换成不含 rubric 原文的内部评分证据。"""
    verdict = assessment.verdict
    score = None
    if rubric is not None and verdict != "ungradable":
        score = (
            1.0
            if verdict == "correct"
            else (
                0.0
                if verdict == "incorrect"
                else weighted_criterion_score(rubric, assessment)
            )
        )
    error_tags = [tag.value for tag in assessment.error_tags]
    evidence_id = (
        assessment.evidence_id or f"open:{context.run_id}:{attempt['question_id']}"
    )
    return {
        "verdict": verdict,
        "question_id": attempt["question_id"],
        "knowledge_point_ids": list(attempt.get("knowledge_point_ids") or []),
        "subject_id": attempt.get("subject_id"),
        "evidence_id": evidence_id,
        "score": score,
        "error_types": error_tags,
        "error_tags": error_tags,
        "answer_source": attempt.get("answer_source"),
        "assessment_source": "llm_rubric",
        "evidence_type": "open_response",
        "assessment_confidence": assessment.assessment_confidence,
        "model_version": OPEN_ANSWER_ASSESSOR_VERSION,
        "hint_levels_used": list(attempt.get("hint_levels_used") or []),
        "answer_exposed": bool(attempt.get("answer_exposed", False)),
        "answer_confidence": attempt.get("answer_confidence"),
        "rubric_version": rubric.version if rubric is not None else "rubric-missing",
        "criterion_scores": [
            item.model_dump(mode="json") for item in assessment.criterion_scores
        ],
        "feedback_reason": assessment.feedback_reason,
        "knowledge_point_coverage": (
            {
                point_id: round(1.0 / len(attempt["knowledge_point_ids"]), 6)
                for point_id in dict.fromkeys(attempt.get("knowledge_point_ids") or [])
            }
            if attempt.get("knowledge_point_ids")
            else {}
        ),
    }


async def _open_answer_assessment_node(
    context: ExecutionContext, db: AsyncSession
) -> NodeResult:
    """调用受控 Assessor；rubric/低置信度失败收敛为 ungradable。"""
    attempt = context.get("attempt", {})
    raw_rubric = attempt.get("rubric")
    try:
        rubric = OpenAnswerRubric.model_validate(raw_rubric) if raw_rubric else None
    except ValueError:
        rubric = None
    evidence_id = stable_open_answer_evidence_id(
        run_id=context.run_id,
        question_id=str(attempt.get("question_id") or "unknown"),
    )
    if rubric is None or not rubric.is_complete:
        assessment = OpenAnswerAssessment(
            verdict="ungradable",
            assessment_confidence=0.0,
            evidence_id=evidence_id,
            feedback_reason="rubric 不完整，暂时无法安全评分",
        )
    else:
        try:
            context.charge_model_call()
            assessment = await open_answer_assessor_runtime.assess(
                question={
                    "id": attempt.get("question_id"),
                    "type": attempt.get("question_type"),
                    "content": attempt.get("question_content"),
                    "options": attempt.get("options") or [],
                    "knowledge_point_ids": list(
                        attempt.get("knowledge_point_ids") or []
                    ),
                },
                rubric=rubric,
                user_answer=str(attempt.get("user_answer") or ""),
                hint_levels_used=tuple(attempt.get("hint_levels_used") or []),
                answer_exposed=bool(attempt.get("answer_exposed", False)),
                deps=OpenAnswerAssessorDeps(
                    run_id=context.run_id,
                    user_id=context.user_id,
                    question_id=str(attempt["question_id"]),
                    rubric_version=rubric.version,
                ),
                db=db,
            )
            assessment = normalize_open_answer_assessment(
                assessment,
                deps=OpenAnswerAssessorDeps(
                    run_id=context.run_id,
                    user_id=context.user_id,
                    question_id=str(attempt["question_id"]),
                    rubric_version=rubric.version,
                ),
                rubric=rubric,
            )
        except Exception as error:
            logger.warning(
                "开放回答评估失败，收敛为 ungradable",
                run_id=context.run_id,
                question_id=attempt.get("question_id"),
                error=str(error),
            )
            assessment = OpenAnswerAssessment(
                verdict="ungradable",
                assessment_confidence=0.0,
                evidence_id=evidence_id,
                feedback_reason="暂时无法完成评分，需要更明确回答",
            )
    grading_evidence = _open_answer_grading_evidence(
        context,
        attempt,
        assessment,
        rubric,
    )
    context.set("open_assessment", assessment.model_dump(mode="json"))
    context.set("grading_evidence", grading_evidence)
    return NodeResult.success(
        {
            "assessed": True,
            "verdict": assessment.verdict,
            "assessment_confidence": assessment.assessment_confidence,
        },
        next_node="rubric_gate",
    )


async def _rubric_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """rubric 校验"""
    if context.get("open_assessment") is not None:
        grading = context.get("grading_evidence") or {}
        if grading.get("verdict") not in {
            "correct",
            "partial",
            "incorrect",
            "ungradable",
        }:
            return NodeResult.failure("开放回答评估结果不合法")
        context.set(
            "rubric",
            {
                "complete": grading.get("rubric_version") != "rubric-missing",
                "version": grading.get("rubric_version"),
                "assessment_source": grading.get("assessment_source"),
            },
        )
        return NodeResult.success({"gate_passed": True}, next_node="generate_feedback")

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


async def _generate_feedback_node(
    context: ExecutionContext, db: AsyncSession
) -> NodeResult:
    """根据确定性判定生成有证据的反馈"""
    attempt = context.get("attempt", {})
    result = context.get("objective_result", {})
    grading_evidence = context.get("grading_evidence") or {}
    if context.get("open_assessment") is not None:
        verdict = grading_evidence.get("verdict")
        error_tags = grading_evidence.get("error_tags") or []
        if verdict == "ungradable":
            feedback = {
                "overall": "需要更明确回答",
                "strengths": [],
                "weaknesses": [
                    grading_evidence.get("feedback_reason")
                    or "当前回答无法与完整 rubric 可靠对应"
                ],
                "suggestions": ["请补充关键概念、推理步骤和适用条件后再提交一次。"],
            }
        elif verdict == "correct":
            feedback = {
                "overall": "回答正确",
                "strengths": ["回答覆盖了冻结 rubric 的全部评分标准"],
                "weaknesses": [],
                "suggestions": ["可以继续完成一道变式题，验证知识能否迁移。"],
            }
        elif verdict == "partial":
            feedback = {
                "overall": "回答部分正确",
                "strengths": ["回答覆盖了部分评分标准"],
                "weaknesses": [
                    (
                        f"仍需补充或修正：{', '.join(error_tags)}"
                        if error_tags
                        else "仍有评分标准没有完整覆盖"
                    )
                ],
                "suggestions": ["请针对未覆盖的评分标准补充完整推理。"],
            }
        else:
            feedback = {
                "overall": "回答需要修正",
                "strengths": [],
                "weaknesses": [
                    (
                        f"未满足开放题评分标准：{', '.join(error_tags)}"
                        if error_tags
                        else "回答与冻结 rubric 的核心要求不一致"
                    )
                ],
                "suggestions": ["请重新梳理核心概念和推理步骤后再作答。"],
            }
        context.set("feedback", feedback)
        logger.info("开放回答反馈生成", run_id=context.run_id, verdict=verdict)
        return NodeResult.success(
            {"feedback_generated": True}, next_node="feedback_gate"
        )

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
                (
                    f"你的答案是 {attempt.get('user_answer')}，"
                    f"标准答案是 {attempt.get('standard_answer')}"
                )
            ],
            "suggestions": [attempt.get("explanation") or "请结合标准答案复盘错误原因"],
        }
    )
    context.set("feedback", feedback)
    logger.info("反馈生成", run_id=context.run_id, feedback_summary=feedback["overall"])
    return NodeResult.success({"feedback_generated": True}, next_node="feedback_gate")


async def _feedback_gate_node(
    context: ExecutionContext, db: AsyncSession
) -> NodeResult:
    """反馈证据校验"""
    feedback = context.get("feedback", {})

    if not feedback.get("overall"):
        logger.warning("反馈为空", run_id=context.run_id)
        return NodeResult.failure("反馈生成失败")

    logger.info("反馈校验通过", run_id=context.run_id)
    return NodeResult.success({"gate_passed": True}, next_node="render_artifact")


async def _render_artifact_node(
    context: ExecutionContext, db: AsyncSession
) -> NodeResult:
    """渲染反馈产物"""
    feedback = context.get("feedback", {})
    teaching_policy = load_frozen_teaching_policy(
        context,
        workflow_action="grade",
    )

    content = {
        "overall": feedback.get("overall", ""),
        "strengths": feedback.get("strengths", []),
        "weaknesses": feedback.get("weaknesses", []),
        "suggestions": feedback.get("suggestions", []),
    }
    # 客观题和开放题都必须只携带服务端已确认的结构化评分证据。
    grading_evidence = context.get("grading_evidence") or {}
    if grading_evidence.get("verdict"):
        content["grading"] = grading_evidence

    artifact = {
        "type": "feedback",
        "title": "批改反馈",
        "content": content,
        "summary": feedback.get("overall", "反馈已生成"),
        "_private_metadata": {
            "teaching_policy": teaching_policy.model_dump(mode="json"),
        },
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

    wf.add_node(
        Node(
            name="load_attempt_snapshot",
            node_type="action",
            execute=_load_attempt_snapshot_node,
            description="加载作答",
        )
    )
    wf.add_node(
        Node(
            name="objective_grade",
            node_type="gate",
            execute=_objective_grade_node,
            description="客观题判定",
        )
    )
    wf.add_node(
        Node(
            name="open_answer_assessment",
            node_type="action",
            execute=_open_answer_assessment_node,
            description="开放回答 rubric 评估",
        )
    )
    wf.add_node(
        Node(
            name="rubric_gate",
            node_type="gate",
            execute=_rubric_gate_node,
            description="rubric校验",
        )
    )
    wf.add_node(
        Node(
            name="generate_feedback",
            node_type="action",
            execute=_generate_feedback_node,
            description="生成反馈",
        )
    )
    wf.add_node(
        Node(
            name="feedback_gate",
            node_type="gate",
            execute=_feedback_gate_node,
            description="反馈校验",
        )
    )
    wf.add_node(
        Node(
            name="render_artifact",
            node_type="render",
            execute=_render_artifact_node,
            description="渲染产物",
        )
    )
    wf.add_node(
        Node(
            name="completed",
            node_type="render",
            execute=_completed_node,
            description="完成",
        )
    )

    wf.add_edge("load_attempt_snapshot", ["objective_grade", "open_answer_assessment"])
    wf.add_edge("objective_grade", ["rubric_gate"])
    wf.add_edge("open_answer_assessment", ["rubric_gate"])
    wf.add_edge("rubric_gate", ["generate_feedback"])
    wf.add_edge("generate_feedback", ["feedback_gate"])
    wf.add_edge("feedback_gate", ["render_artifact"])
    wf.add_edge("render_artifact", ["completed"])

    return wf


# 注册
workflow_registry.register(build_grade_workflow())
