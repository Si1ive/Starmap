"""
validate@v1 工作流（用题验证）

load_learning_evidence -> question_discovery -> question_gate | generate_question ->
composition_gate -> create_draft -> render_artifact -> completed
"""

from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, Node, NodeResult, ExecutionContext
from .registry import workflow_registry
from ..service import AgentService
from ..memory_selector import (
    build_practice_filters,
    build_practice_query,
    load_practice_bundle,
)
from ..model_runtime.practice import PracticeGenerationDeps, practice_generation_runtime
from ..time_utils import utc_isoformat, utc_now

logger = get_logger(__name__)

_PRACTICE_TOPIC_INPUT_KEY = "practice_topic"
_PRACTICE_TOPIC_PROMPT = "请补充想练习的知识点或题目范围"


def _question_is_eligible(candidate: Dict[str, Any]) -> bool:
    meta = candidate.get("question_meta") or {}
    entity = candidate.get("entity") or {}
    review_status = entity.get("review_status") or meta.get("review_status")
    status = entity.get("status") or meta.get("status")
    if candidate.get("entity_type") != "question":
        return False
    if review_status == "rejected":
        return False
    if status == "deleted":
        return False
    if not meta.get("question_type") or not meta.get("difficulty"):
        return False
    has_source = bool(meta.get("source") or meta.get("paper_name"))
    answer_source = meta.get("answer_source")
    return has_source or answer_source in {"extracted", "manual", "llm"}


async def _load_learning_evidence_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """读取用户学习证据"""
    practice_bundle = await load_practice_bundle(
        db,
        run_id=context.run_id,
        user_id=context.user_id,
    )
    topic = practice_bundle.topic
    weak_areas = (
        [topic.title]
        if topic is not None
        else list(context.get("weak_areas", []) or [])
    )
    recent_topics = (
        [topic.title]
        if topic is not None
        else context.get("recent_topics", [])
    )
    # P1 简化：从上下文获取
    evidence = {
        "user_id": context.user_id,
        "weak_areas": weak_areas,
        "strong_areas": context.get("strong_areas", ["计算机网络"]),
        "recent_topics": recent_topics,
    }
    context.set("practice_bundle", practice_bundle.model_dump(mode="json"))
    context.set("learning_evidence", evidence)
    logger.info("学习证据加载", run_id=context.run_id, weak_areas=evidence["weak_areas"])
    return NodeResult.success({"evidence_loaded": True}, next_node="question_discovery")


async def _question_discovery_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """检索候选题"""
    from ..tools.retrieve_knowledge import retrieve_knowledge

    evidence = context.get("learning_evidence", {})
    weak_areas = evidence.get("weak_areas", [])
    practice_bundle = context.get("practice_bundle", {})
    unresolved_constraints = (practice_bundle or {}).get("unresolved_constraints") or []
    if unresolved_constraints:
        logger.warning(
            "Validate 无法解析显式范围",
            run_id=context.run_id,
            unresolved_constraints=unresolved_constraints,
        )
        context.set("candidates", [])
        return NodeResult.failure("无法解析显式章节范围，请提供有效章节")

    # 检索候选题目
    query = build_practice_query(
        practice_bundle if isinstance(practice_bundle, dict) else {},
        weak_areas,
    )
    if not query.strip():
        agent_input = await AgentService(db).get_input(
            context.run_id,
            _PRACTICE_TOPIC_INPUT_KEY,
        )
        if agent_input and agent_input.status == "answered":
            clarified_topic = str(agent_input.answer_ref or "").strip()
            if clarified_topic:
                weak_areas = [clarified_topic]
                updated_evidence = dict(evidence)
                updated_evidence["weak_areas"] = weak_areas
                updated_evidence["recent_topics"] = weak_areas
                context.set("learning_evidence", updated_evidence)
                context.set("clarified_practice_topic", clarified_topic)
                query = build_practice_query(
                    practice_bundle if isinstance(practice_bundle, dict) else {},
                    weak_areas,
                )
                logger.info(
                    "Validate 使用澄清主题继续检索",
                    run_id=context.run_id,
                    clarified_topic=clarified_topic,
                )
        if not query.strip():
            if agent_input is None:
                await AgentService(db).create_input(
                    context.run_id,
                    _PRACTICE_TOPIC_INPUT_KEY,
                    _PRACTICE_TOPIC_PROMPT,
                )
            logger.warning("Validate 缺少主题，进入澄清", run_id=context.run_id)
            context.set("candidates", [])
            return NodeResult.waiting(
                next_node="question_discovery",
                output={
                    "waiting_for_user": True,
                    "missing_practice_topic": True,
                    "clarification_input_key": _PRACTICE_TOPIC_INPUT_KEY,
                },
            )

    result = await retrieve_knowledge(
        db,
        query=query,
        knowledge_point_ids=(practice_bundle or {}).get("knowledge_point_ids"),
        chapter_ids=(practice_bundle or {}).get("chapter_ids"),
        strict_chapter_scope=(
            (practice_bundle or {}).get("chapter_scope_source") == "explicit"
        ),
        filters=build_practice_filters(practice_bundle),
        exclude_entity_ids=(practice_bundle or {}).get("excluded_question_ids"),
        entity_type="question",
        limit=10,
        run_id=context.run_id,
    )
    
    candidates = result.get("results", [])
    context.set("candidates", candidates)
    logger.info("候选题检索", run_id=context.run_id, count=len(candidates))
    if not candidates:
        notice = "题库中未找到合适真题，将由模型生成一道练习题"
        context.set("retrieval_notice", notice)
        logger.info("候选题为空，转入模型生成", run_id=context.run_id)
        return NodeResult.success(
            {
                "questions_found": 0,
                "fallback": "llm_generation",
                "notice": notice,
            },
            next_node="generate_question",
        )
    return NodeResult.success({"questions_found": len(candidates)}, next_node="question_gate")


async def _question_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """题目资格校验"""
    candidates = context.get("candidates", [])
    
    valid = [q for q in candidates if _question_is_eligible(q)]
    
    # 检索有返回但都不满足资格时仍属于可恢复的题库不足，而非运行失败。
    if not valid:
        notice = "题库候选均未通过资格检查，将由模型生成一道练习题"
        context.set("retrieval_notice", notice)
        logger.info("无有效候选题，转入模型生成", run_id=context.run_id)
        return NodeResult.success(
            {
                "gate_passed": False,
                "fallback": "llm_generation",
                "notice": notice,
            },
            next_node="generate_question",
        )
    
    context.set("valid_questions", valid[:5])  # 最多取5道
    logger.info("题目校验通过", run_id=context.run_id, valid_count=len(valid))
    return NodeResult.success({"gate_passed": True}, next_node="composition_gate")


async def _generate_question_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """题库无合格题目时生成一道结构化单选题。"""
    from .contracts import ModelBudgetExceeded

    bundle = context.get("practice_bundle") or {}
    topic = (bundle.get("topic") or {}).get("title")
    if not topic:
        weak_areas = (context.get("learning_evidence") or {}).get("weak_areas") or []
        topic = weak_areas[0] if weak_areas else None
    if not topic:
        return NodeResult.failure("缺少生成练习题所需的明确主题")

    try:
        context.charge_model_call()
    except ModelBudgetExceeded as error:
        return NodeResult.failure(str(error))

    generated = await practice_generation_runtime.generate(
        deps=PracticeGenerationDeps(
            run_id=context.run_id,
            user_id=context.user_id,
            topic=str(topic),
            difficulty=str(bundle.get("difficulty") or "medium"),
        ),
        db=db,
    )
    question_id = f"generated_{context.run_id}"
    candidate = {
        "entity_id": question_id,
        "entity_type": "question",
        "entity_title": f"{topic} · 模型生成练习题",
        "content_text": generated.content,
        "subject_id": None,
        "source": {"title": "Agent 模型即时生成"},
        "question_meta": {
            "question_type": "choice",
            "difficulty": generated.difficulty,
            "source": "Agent 模型即时生成",
            "paper_name": None,
            "answer_source": "llm",
            "review_status": "generated",
            "status": "active",
            "options": [option.model_dump(mode="json") for option in generated.options],
            "answer": generated.answer,
            "explanation": generated.explanation,
            "generated": True,
            "topic": str(topic),
        },
    }
    context.set("valid_questions", [candidate])
    logger.info("模型练习题生成完成", run_id=context.run_id, topic=topic)
    return NodeResult.success(
        {
            "generated": True,
            "question_id": question_id,
            "notice": context.get("retrieval_notice"),
        },
        next_node="composition_gate",
    )


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
        meta = q.get("question_meta") or {}
        q_type = meta.get("question_type", "unknown")
        difficulty = meta.get("difficulty", "unknown")
        subject = q.get("subject_id") or "unknown"
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
        "created_at": utc_isoformat(utc_now()),
    }
    
    context.set("practice_draft", draft)
    logger.info("练习草稿创建", run_id=context.run_id, question_count=len(valid_questions))
    return NodeResult.success({"draft_created": True}, next_node="render_artifact")


async def _render_artifact_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """渲染练习产物"""
    draft = context.get("practice_draft", {})
    composition = context.get("composition", {})
    question_ids = [
        str(question.get("entity_id"))
        for question in draft.get("questions", [])
        if question.get("entity_id")
    ]
    questions = draft.get("questions", [])
    markdown_sections = []
    generated_questions = []
    for index, question in enumerate(questions, start=1):
        meta = question.get("question_meta") or {}
        content = str(question.get("content_text") or question.get("entity_title") or "").strip()
        options = list(meta.get("options") or [])
        lines = [f"### 第 {index} 题", "", content]
        if options:
            lines.extend(
                ["", *[f"- {option.get('key')}. {option.get('text')}" for option in options]]
            )
        markdown_sections.append("\n".join(lines))
        if meta.get("generated"):
            generated_questions.append(
                {
                    "id": question.get("entity_id"),
                    "question_type": meta.get("question_type"),
                    "content": content,
                    "options": options,
                    "standard_answer": meta.get("answer"),
                    "answer_source": "llm",
                    "explanation": meta.get("explanation"),
                    "difficulty": meta.get("difficulty"),
                    "topic": meta.get("topic"),
                }
            )
    markdown = "\n\n".join(markdown_sections)
    if context.get("retrieval_notice"):
        markdown = f"> {context.get('retrieval_notice')}。\n\n{markdown}"

    artifact = {
        "type": "practice",
        "title": draft.get("title", "专项练习"),
        "content": {
            "content": markdown,
            "question_count": len(draft.get("questions", [])),
            "question_ids": question_ids,
            "composition": composition,
        },
        "summary": f"共 {len(draft.get('questions', []))} 道题，覆盖 {len(composition.get('subjects', {}))} 个考点",
        "_private_metadata": {"generated_questions": generated_questions},
    }
    
    logger.info("产物渲染完成", run_id=context.run_id)
    return NodeResult.success(
        {"artifact_ready": True, "question_count": len(question_ids)},
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
    wf.add_node(Node(name="generate_question", node_type="action", execute=_generate_question_node, description="模型生成题目"))
    wf.add_node(Node(name="composition_gate", node_type="gate", execute=_composition_gate_node, description="组合校验"))
    wf.add_node(Node(name="create_draft", node_type="action", execute=_create_draft_node, description="创建草稿"))
    wf.add_node(Node(name="render_artifact", node_type="render", execute=_render_artifact_node, description="渲染产物"))
    wf.add_node(Node(name="completed", node_type="render", execute=_completed_node, description="完成"))
    
    wf.add_edge("load_learning_evidence", ["question_discovery"])
    wf.add_edge("question_discovery", ["question_gate", "generate_question"])
    wf.add_edge("question_gate", ["composition_gate", "generate_question"])
    wf.add_edge("generate_question", ["composition_gate"])
    wf.add_edge("composition_gate", ["create_draft"])
    wf.add_edge("create_draft", ["render_artifact"])
    wf.add_edge("render_artifact", ["completed"])
    
    return wf


# 注册
workflow_registry.register(build_validate_workflow())
