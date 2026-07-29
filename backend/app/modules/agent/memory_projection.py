"""Project trusted Agent facts into layered long-term memory."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.learning.evidence import (
    EvidenceGate,
    EvidenceGateError,
    build_assessment_evidence,
    finalize_evidence_weight,
)
from .memory_contracts import MemoryFactType
from .models import (
    AgentApproval,
    AgentArtifact,
    AgentMemoryEvent,
    AgentMemoryUpdateOutbox,
    AgentRun,
    UserLearningMastery,
)
from .mastery_projector import MasteryProjector
from .time_utils import utc_now

logger = get_logger(__name__)


async def _ensure_memory_update_outbox(
    db: AsyncSession,
    run: AgentRun,
    memory_event: AgentMemoryEvent,
) -> None:
    """确保每个 Run/事实类型只有一个待异步投影任务。"""
    existing = await db.scalar(
        select(AgentMemoryUpdateOutbox.id).where(
            AgentMemoryUpdateOutbox.run_id == run.id,
            AgentMemoryUpdateOutbox.event_type == memory_event.fact_type,
        )
    )
    if existing is not None:
        return
    try:
        async with db.begin_nested():
            db.add(
                AgentMemoryUpdateOutbox(
                    run_id=run.id,
                    thread_id=run.thread_id,
                    user_id=run.user_id,
                    event_type=memory_event.fact_type,
                    status="pending",
                    payload_json={
                        "memory_event_id": memory_event.id,
                        "fact_type": memory_event.fact_type,
                    },
                )
            )
            await db.flush()
    except IntegrityError:
        # 并发重放由 (run_id, event_type) 唯一约束收敛；SAVEPOINT
        # 只回滚重复 Outbox，不污染外层成功 Run/事实事务。
        logger.info(
            "Memory Outbox 并发幂等命中",
            run_id=run.id,
            event_type=memory_event.fact_type,
        )


async def project_topic_confirmed_fact(
    db: AsyncSession,
    run: AgentRun,
    *,
    snapshot_id: str,
    state_version: int,
    source_message_id: str | None,
    topic: dict,
) -> None:
    """把本轮用户显式选择的主题记为线程事实。

    从线程热状态继承的主题只代表本轮读取了旧事实，不重复写“用户确认”。
    该投影发生在 Router 调用前，因此后续模型失败也不会丢失用户已表达的主题。
    """
    if topic.get("source") != "context_ref":
        return
    entity_type = str(topic.get("entity_type") or "").strip()
    title = str(topic.get("title") or "").strip()
    if not entity_type or not title:
        return

    fact_type = MemoryFactType.TOPIC_CONFIRMED.value
    idempotency_key = f"{fact_type}:{run.id}"
    existing = await db.scalar(
        select(AgentMemoryEvent).where(
            AgentMemoryEvent.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        await _ensure_memory_update_outbox(db, run, existing)
        return

    memory_event = AgentMemoryEvent(
        user_id=run.user_id,
        thread_id=run.thread_id,
        run_id=run.id,
        memory_scope="thread",
        source_kind="message",
        fact_type=fact_type,
        idempotency_key=idempotency_key,
        payload_json={
            "snapshot_id": snapshot_id,
            "state_version": state_version,
            "source_message_id": source_message_id,
            "topic": topic,
        },
    )
    db.add(memory_event)
    await db.flush()
    await _ensure_memory_update_outbox(db, run, memory_event)
    logger.info(
        "用户确认主题事实写入",
        run_id=run.id,
        snapshot_id=snapshot_id,
        topic=title,
    )


async def project_completed_run_facts(
    db: AsyncSession,
    run: AgentRun,
    artifact: AgentArtifact | None,
) -> None:
    """在 Run 完成事务内按产物类型写事实事件；不按 workflow 名分派。"""
    if artifact is None:
        return
    if artifact.artifact_type == "explanation":
        await _record_explanation_artifact_created(db, run, artifact)
    elif artifact.artifact_type == "plan":
        await _record_plan_confirmed(db, run, artifact)
    elif artifact.artifact_type == "practice":
        await _record_practice_artifact_created(db, run, artifact)
    elif artifact.artifact_type == "feedback":
        await _record_grade_result_confirmed(db, run, artifact)


async def _record_explanation_artifact_created(
    db: AsyncSession,
    run: AgentRun,
    artifact: AgentArtifact,
) -> None:
    """记录讲解产物事实，不复制正文，也不推导学习掌握度。"""
    fact_type = MemoryFactType.EXPLANATION_ARTIFACT_CREATED.value
    idempotency_key = f"{fact_type}:{run.id}"
    existing = await db.scalar(
        select(AgentMemoryEvent).where(
            AgentMemoryEvent.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        await _ensure_memory_update_outbox(db, run, existing)
        return

    memory_event = AgentMemoryEvent(
        user_id=run.user_id,
        thread_id=run.thread_id,
        run_id=run.id,
        memory_scope="thread",
        source_kind="artifact",
        fact_type=fact_type,
        idempotency_key=idempotency_key,
        payload_json={
            "artifact_id": artifact.id,
            "memory_snapshot_id": (run.metadata_json or {}).get(
                "memory_snapshot_id"
            ),
        },
    )
    db.add(memory_event)
    await db.flush()
    from app.modules.learning.events import record_explanation_activity

    await record_explanation_activity(db, run=run, artifact=artifact)
    await _ensure_memory_update_outbox(db, run, memory_event)
    logger.info(
        "讲解产物事实写入",
        run_id=run.id,
        artifact_id=artifact.id,
    )


async def _record_plan_confirmed(
    db: AsyncSession,
    run: AgentRun,
    artifact: AgentArtifact,
) -> None:
    """只有数据库中真实批准并已产出 Artifact 的计划才进入长期事实。"""
    content = artifact.content_json or {}
    approval_id = str(content.get("approval_id") or "").strip()
    if not approval_id:
        logger.warning(
            "计划产物缺少审批 ID，跳过长期目标事实",
            run_id=run.id,
            artifact_id=artifact.id,
        )
        return
    approval = await db.scalar(
        select(AgentApproval).where(
            AgentApproval.id == approval_id,
            AgentApproval.run_id == run.id,
            AgentApproval.status == "approved",
        )
    )
    if approval is None:
        logger.warning(
            "计划产物没有有效批准事实，跳过长期目标",
            run_id=run.id,
            artifact_id=artifact.id,
            approval_id=approval_id,
        )
        return

    fact_type = MemoryFactType.PLAN_CONFIRMED.value
    idempotency_key = f"{fact_type}:{approval_id}"
    existing = await db.scalar(
        select(AgentMemoryEvent).where(
            AgentMemoryEvent.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        await _ensure_memory_update_outbox(db, run, existing)
        return

    memory_event = AgentMemoryEvent(
        user_id=run.user_id,
        thread_id=run.thread_id,
        run_id=run.id,
        memory_scope="user",
        source_kind="artifact",
        fact_type=fact_type,
        idempotency_key=idempotency_key,
        payload_json={
            "artifact_id": artifact.id,
            "approval_id": approval_id,
            "memory_snapshot_id": (run.metadata_json or {}).get(
                "memory_snapshot_id"
            ),
        },
    )
    db.add(memory_event)
    await db.flush()
    await _ensure_memory_update_outbox(db, run, memory_event)
    logger.info(
        "用户确认计划事实写入",
        run_id=run.id,
        artifact_id=artifact.id,
        approval_id=approval_id,
    )


async def _record_practice_artifact_created(
    db: AsyncSession,
    run: AgentRun,
    artifact: AgentArtifact,
) -> None:
    content = artifact.content_json or {}
    question_ids = [
        str(question_id).strip()
        for question_id in ((content.get("content") or {}).get("question_ids") or [])
        if str(question_id).strip()
    ]
    if not question_ids:
        logger.warning(
            "练习产物缺少题目 ID，跳过排除集事实事件",
            run_id=run.id,
            artifact_id=artifact.id,
        )
        return

    fact_type = MemoryFactType.PRACTICE_ARTIFACT_CREATED.value
    idempotency_key = f"{fact_type}:{run.id}"
    existing = await db.scalar(
        select(AgentMemoryEvent).where(
            AgentMemoryEvent.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        await _ensure_memory_update_outbox(db, run, existing)
        return

    memory_event = AgentMemoryEvent(
        user_id=run.user_id,
        thread_id=run.thread_id,
        run_id=run.id,
        memory_scope="user",
        source_kind="artifact",
        fact_type=fact_type,
        idempotency_key=idempotency_key,
        payload_json={
            "artifact_id": artifact.id,
            "question_ids": question_ids,
        },
    )
    db.add(memory_event)
    await db.flush()
    await _ensure_memory_update_outbox(db, run, memory_event)
    logger.info(
        "练习事实事件写入",
        run_id=run.id,
        artifact_id=artifact.id,
        question_count=len(question_ids),
    )


async def _record_grade_result_confirmed(
    db: AsyncSession,
    run: AgentRun,
    artifact: AgentArtifact,
) -> None:
    """只有携带结构化真实评分证据的反馈产物才回写掌握度。

    掌握度更新与事实事件在同一事务内，以证据 ID 做幂等键：
    重放同一证据不会重复计数，也不会重复写事件。
    """
    content = artifact.content_json or {}
    grading = (content.get("content") or {}).get("grading") or {}
    verdict = str(grading.get("verdict") or "").strip().lower()
    question_id = str(grading.get("question_id") or "").strip()
    # 外部评分载荷可能重复携带同一知识点；保持首次出现顺序并去重，
    # 避免一条证据重复累计，或为新用户插入重复的唯一键记录。
    knowledge_point_ids = list(
        dict.fromkeys(
            normalized
            for kp_id in grading.get("knowledge_point_ids") or []
            if (normalized := str(kp_id).strip())
        )
    )
    if (
        verdict not in {"correct", "partial", "incorrect"}
        or not question_id
        or not knowledge_point_ids
    ):
        logger.info(
            "反馈产物缺少结构化评分证据，跳过掌握度回写",
            run_id=run.id,
            artifact_id=artifact.id,
        )
        return

    evidence_id = str(grading.get("evidence_id") or run.id)
    fact_type = MemoryFactType.GRADE_RESULT_CONFIRMED.value
    # evidence_id 由评分来源提供，不假设它跨用户全局唯一。
    idempotency_key = f"{fact_type}:{run.user_id}:{evidence_id}"
    existing = await db.scalar(
        select(AgentMemoryEvent).where(
            AgentMemoryEvent.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        await _ensure_memory_update_outbox(db, run, existing)
        return

    generated_question = (
        str(grading.get("assessment_source") or "").strip().lower()
        == "generated_question"
        or str(question_id).startswith("generated_")
    )
    evidence = build_assessment_evidence(
        source_id=evidence_id,
        source_type="agent_grade",
        verdict=verdict,
        question_id=question_id,
        knowledge_point_ids=knowledge_point_ids,
        answer_source=(
            "generated_question"
            if generated_question
            else grading.get("answer_source") or "manual"
        ),
        assessment_source=grading.get("assessment_source")
        or ("generated_question" if generated_question else "deterministic"),
        hint_levels_used=list(grading.get("hint_levels_used") or []),
        answer_exposed=bool(grading.get("answer_exposed", False)),
        confidence=grading.get("assessment_confidence", grading.get("confidence", 1.0)),
        model_version=grading.get("model_version"),
        knowledge_point_coverage=grading.get("knowledge_point_coverage"),
        error_tags=grading.get("error_tags") or grading.get("error_types") or [],
        evidence_type=grading.get("evidence_type"),
    )
    try:
        EvidenceGate().validate(
            evidence,
            owner_user_id=run.user_id,
            source_user_id=run.user_id,
            source_run_id=run.id,
            expected_question_id=question_id,
            verified_knowledge_point_ids=knowledge_point_ids,
        )
    except EvidenceGateError as error:
        logger.info(
            "评分证据门禁未通过，跳过掌握度回写",
            run_id=run.id,
            artifact_id=artifact.id,
            reason=str(error),
        )
        return
    evidence, weight = finalize_evidence_weight(
        evidence,
        question_review_status=grading.get("question_review_status"),
        suggested_weight=grading.get("suggested_weight"),
    )

    memory_event = AgentMemoryEvent(
        user_id=run.user_id,
        thread_id=run.thread_id,
        run_id=run.id,
        memory_scope="user",
        source_kind="artifact",
        fact_type=fact_type,
        idempotency_key=idempotency_key,
        payload_json={
            "artifact_id": artifact.id,
            "evidence_id": evidence_id,
            "question_id": question_id,
            "knowledge_point_ids": knowledge_point_ids,
            "verdict": verdict,
            "score": grading.get("score"),
            "error_types": grading.get("error_types") or [],
            "learning_evidence": evidence.to_payload(),
            "evidence_strength": weight.evidence_strength,
            "evidence_weight_policy_version": weight.policy_version,
            "evidence_weight_reasons": list(weight.reasons),
        },
    )
    db.add(memory_event)

    subject_id = str(grading.get("subject_id") or "").strip() or None
    projector = MasteryProjector()
    for kp_id in knowledge_point_ids:
        mastery = await db.scalar(
            select(UserLearningMastery).where(
                UserLearningMastery.user_id == run.user_id,
                UserLearningMastery.knowledge_point_id == kp_id,
            )
        )
        if mastery is None:
            mastery = projector.apply(
                None,
                evidence,
                knowledge_point_id=kp_id,
                user_id=run.user_id,
                subject_id=subject_id,
                evidence_at=artifact.created_at or utc_now(),
                partial_credit=grading.get("score"),
                suggested_weight=grading.get("suggested_weight"),
            )
            db.add(mastery)
        else:
            projector.apply(
                mastery,
                evidence,
                knowledge_point_id=kp_id,
                subject_id=subject_id,
                evidence_at=artifact.created_at or utc_now(),
                partial_credit=grading.get("score"),
                suggested_weight=grading.get("suggested_weight"),
            )

    await db.flush()
    from app.modules.learning.events import record_agent_grade_activity

    await record_agent_grade_activity(
        db,
        run=run,
        artifact=artifact,
        grading=grading,
    )
    await _ensure_memory_update_outbox(db, run, memory_event)
    logger.info(
        "评分事实事件写入并更新掌握度",
        run_id=run.id,
        artifact_id=artifact.id,
        verdict=verdict,
        knowledge_point_count=len(knowledge_point_ids),
    )
