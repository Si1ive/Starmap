"""Project trusted Agent facts into layered long-term memory."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .memory_contracts import MemoryFactType
from .models import AgentArtifact, AgentMemoryEvent, AgentRun, UserLearningMastery
from .time_utils import utc_now

logger = get_logger(__name__)

# 真实评分结论对掌握度的贡献值；不在表内的 verdict 视为无效证据。
_VERDICT_CONTRIBUTIONS = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}


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
        select(AgentMemoryEvent.id).where(
            AgentMemoryEvent.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return

    db.add(
        AgentMemoryEvent(
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
    )
    await db.flush()
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
        select(AgentMemoryEvent.id).where(
            AgentMemoryEvent.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return

    db.add(
        AgentMemoryEvent(
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
    )
    await db.flush()
    logger.info(
        "讲解产物事实写入",
        run_id=run.id,
        artifact_id=artifact.id,
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
        select(AgentMemoryEvent.id).where(
            AgentMemoryEvent.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return

    db.add(
        AgentMemoryEvent(
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
    )
    await db.flush()
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
    if verdict not in _VERDICT_CONTRIBUTIONS or not question_id or not knowledge_point_ids:
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
        select(AgentMemoryEvent.id).where(
            AgentMemoryEvent.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return

    db.add(
        AgentMemoryEvent(
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
            },
        )
    )

    contribution = _VERDICT_CONTRIBUTIONS[verdict]
    subject_id = str(grading.get("subject_id") or "").strip() or None
    for kp_id in knowledge_point_ids:
        mastery = await db.scalar(
            select(UserLearningMastery).where(
                UserLearningMastery.user_id == run.user_id,
                UserLearningMastery.knowledge_point_id == kp_id,
            )
        )
        if mastery is None:
            mastery = UserLearningMastery(
                user_id=run.user_id,
                subject_id=subject_id,
                knowledge_point_id=kp_id,
                mastery_score=0.0,
                evidence_count=0,
                correct_count=0,
                incorrect_count=0,
            )
            db.add(mastery)
        new_count = mastery.evidence_count + 1
        mastery.mastery_score = round(
            (mastery.mastery_score * mastery.evidence_count + contribution) / new_count,
            4,
        )
        mastery.evidence_count = new_count
        if verdict == "correct":
            mastery.correct_count += 1
        elif verdict == "incorrect":
            mastery.incorrect_count += 1
        mastery.last_evidence_id = evidence_id
        mastery.last_graded_at = utc_now()

    await db.flush()
    logger.info(
        "评分事实事件写入并更新掌握度",
        run_id=run.id,
        artifact_id=artifact.id,
        verdict=verdict,
        knowledge_point_count=len(knowledge_point_ids),
    )
