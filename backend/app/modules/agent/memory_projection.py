"""Project completed-run facts into layered long-term memory."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .memory_contracts import MemoryFactType
from .models import AgentArtifact, AgentMemoryEvent, AgentRun

logger = get_logger(__name__)


async def project_completed_run_facts(
    db: AsyncSession,
    run: AgentRun,
    artifact: AgentArtifact | None,
) -> None:
    """在 Run 完成事务内按产物类型写事实事件；不按 workflow 名分派。"""
    if artifact is None:
        return
    if artifact.artifact_type == "practice":
        await _record_practice_artifact_created(db, run, artifact)


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
