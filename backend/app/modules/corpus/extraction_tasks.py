"""Persistent background task orchestration for document entity extraction."""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.mysql import mysql_client
from app.models.mysql_models import Document, EntityExtractionRun
from app.modules.corpus.errors import DocumentNotFoundError
from app.services.entity_extraction_service import EntityExtractionService

logger = get_logger(__name__)

_entity_extraction_tasks: set[asyncio.Task[Any]] = set()


class EntityExtractionTaskService:
    """Create, query, and dispatch durable entity extraction runs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def start(
        self,
        document_id: str,
        *,
        extract_knowledge: bool,
        extract_questions: bool,
        subject_id: Optional[str],
    ) -> Tuple[EntityExtractionRun, bool]:
        document = await self.db.get(
            Document,
            document_id,
            with_for_update=True,
        )
        if not document:
            raise DocumentNotFoundError("文档不存在")

        running_run = await self._get_running_run(document_id)
        if running_run:
            return running_run, False

        run = EntityExtractionRun(
            id=uuid.uuid4().hex[:32],
            document_id=document_id,
            status="running",
            extract_knowledge=extract_knowledge,
            extract_questions=extract_questions,
            subject_id=subject_id,
        )
        self.db.add(run)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        try:
            self._schedule(run.id)
        except Exception as exc:
            run.status = "failed"
            run.error_detail = f"抽取任务派发失败: {str(exc)[:400]}"
            run.completed_at = self._utcnow()
            await self.db.commit()
            raise

        return run, True

    async def get_latest(
        self,
        document_id: str,
    ) -> Optional[EntityExtractionRun]:
        document = await self.db.get(Document, document_id)
        if not document:
            raise DocumentNotFoundError("文档不存在")

        return (
            await self.db.execute(
                select(EntityExtractionRun)
                .where(EntityExtractionRun.document_id == document_id)
                .order_by(EntityExtractionRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _get_running_run(
        self,
        document_id: str,
    ) -> Optional[EntityExtractionRun]:
        return (
            await self.db.execute(
                select(EntityExtractionRun)
                .where(
                    EntityExtractionRun.document_id == document_id,
                    EntityExtractionRun.status == "running",
                )
                .order_by(EntityExtractionRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    def _schedule(self, run_id: str) -> None:
        task = asyncio.create_task(
            self._run_in_background(run_id),
            name=f"entity-extraction-{run_id}",
        )
        _entity_extraction_tasks.add(task)
        task.add_done_callback(_entity_extraction_tasks.discard)

    @staticmethod
    async def _run_in_background(run_id: str) -> None:
        try:
            async with mysql_client.session() as session:
                await EntityExtractionService(
                    session
                ).extract_entities_with_run_id(run_id)
        except Exception as exc:
            logger.error(
                "后台实体抽取任务失败",
                run_id=run_id,
                error=str(exc),
            )

    @staticmethod
    def serialize(run: EntityExtractionRun) -> Dict[str, Any]:
        return {
            "id": run.id,
            "document_id": run.document_id,
            "status": run.status,
            "extract_knowledge": run.extract_knowledge,
            "extract_questions": run.extract_questions,
            "subject_id": run.subject_id,
            "knowledge_count": run.knowledge_count or 0,
            "question_count": run.question_count or 0,
            "error_detail": run.error_detail,
            "result": run.result_json,
            "started_at": (
                run.started_at.isoformat() if run.started_at else None
            ),
            "completed_at": (
                run.completed_at.isoformat() if run.completed_at else None
            ),
            "created_at": (
                run.created_at.isoformat() if run.created_at else None
            ),
            "updated_at": (
                run.updated_at.isoformat() if run.updated_at else None
            ),
        }

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)
