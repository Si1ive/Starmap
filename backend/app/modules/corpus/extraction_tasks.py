"""Persistent background task orchestration for document entity extraction."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.mysql import mysql_client
from app.models.mysql_models import (
    CorpusFile,
    Document,
    EntitySourceLink,
    EntityExtractionRun,
    KnowledgePoint,
    Question,
)
from app.modules.corpus.errors import (
    DocumentNotFoundError,
    EntityExtractionConflictError,
    EntityNotFoundError,
    EntitySourceUnavailableError,
)
from app.modules.corpus.entity_extraction_pipeline import (
    DocumentEntityExtractionPipeline,
)
from app.modules.corpus.entity_reextraction import EntityReextractionService

logger = get_logger(__name__)

_entity_extraction_tasks: set[asyncio.Task[Any]] = set()


class EntityExtractionRunExecutor:
    """Execute a durable extraction run and persist its final state."""

    def __init__(
        self,
        db: AsyncSession,
        pipeline: Optional[DocumentEntityExtractionPipeline] = None,
        entity_reextraction: Optional[EntityReextractionService] = None,
    ):
        self.db = db
        self.pipeline = pipeline or DocumentEntityExtractionPipeline(db)
        self.entity_reextraction = (
            entity_reextraction or EntityReextractionService(db)
        )

    async def execute(self, run_id: str) -> Dict[str, Any]:
        """Run extraction and indexing for an existing run record."""
        run = await self.db.get(EntityExtractionRun, run_id)
        if not run:
            raise ValueError(f"抽取任务不存在: {run_id}")

        is_entity_run = getattr(run, "scope", "document") == "entity"
        try:
            if is_entity_run:
                result = await self.entity_reextraction.reextract(
                    document_id=run.document_id,
                    entity_type=run.target_entity_type,
                    entity_id=run.target_entity_id,
                )
                indexing_result = await self.index_entity(
                    entity_type=run.target_entity_type,
                    entity_id=run.target_entity_id,
                )
            else:
                await self.set_corpus_file_status(
                    run.document_id,
                    "extracting",
                )
                await self.db.commit()

                result = await self.pipeline.extract(
                    document_id=run.document_id,
                    extract_knowledge=run.extract_knowledge,
                    extract_questions=run.extract_questions,
                    fallback_subject_id=run.subject_id,
                )
                indexing_result = await self.index_document_entities(
                    document_id=run.document_id,
                    include_knowledge=run.extract_knowledge,
                    include_questions=run.extract_questions,
                )
            result = {**result, "indexing": indexing_result}

            run.status = "success"
            run.knowledge_count = int(result.get("knowledge_count") or 0)
            run.question_count = int(result.get("question_count") or 0)
            run.result_json = json.loads(
                json.dumps(result, ensure_ascii=False, default=str)
            )
            run.error_detail = None
            run.completed_at = self._utcnow()
            if not is_entity_run:
                await self.set_corpus_file_status(
                    run.document_id,
                    "indexed",
                )
            await self.db.commit()
            return result
        except Exception as exc:
            await self.db.rollback()
            failed_run = await self.db.get(EntityExtractionRun, run_id)
            if failed_run:
                failed_run.status = "failed"
                failed_run.error_detail = str(exc)[:4000]
                failed_run.completed_at = self._utcnow()
                if not is_entity_run:
                    await self.set_corpus_file_status(
                        failed_run.document_id,
                        "failed",
                        error_detail=str(exc)[:4000],
                    )
                await self.db.commit()
            raise

    async def index_document_entities(
        self,
        document_id: str,
        include_knowledge: bool,
        include_questions: bool,
    ) -> Dict[str, Any]:
        """Build searchable segments immediately after extraction."""
        from app.modules.retrieval.segment_service import SegmentService

        return await SegmentService(self.db).build_document_segments(
            document_id=document_id,
            include_knowledge=include_knowledge,
            include_questions=include_questions,
            rebuild=True,
        )

    async def index_entity(
        self,
        *,
        entity_type: str,
        entity_id: str,
    ) -> Dict[str, Any]:
        """Rebuild searchable segments only for the replaced entity."""
        from app.modules.retrieval.segment_service import SegmentService

        return await SegmentService(self.db).rebuild_entity_segments(
            entity_type=entity_type,
            entity_id=entity_id,
        )

    async def set_corpus_file_status(
        self,
        document_id: str,
        status: str,
        error_detail: Optional[str] = None,
    ) -> None:
        """Update the corpus file associated with a document."""
        document = await self.db.get(Document, document_id)
        if not document or not document.corpus_file_id:
            return

        corpus_file = await self.db.get(
            CorpusFile,
            document.corpus_file_id,
        )
        if not corpus_file:
            return
        corpus_file.status = status
        corpus_file.error_detail = error_detail

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)


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
            scope="document",
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

    async def start_entity(
        self,
        document_id: str,
        *,
        entity_type: str,
        entity_id: str,
    ) -> Tuple[EntityExtractionRun, bool]:
        """Create a durable task for one traceable extracted entity."""
        document = await self.db.get(
            Document,
            document_id,
            with_for_update=True,
        )
        if not document:
            raise DocumentNotFoundError("文档不存在")

        entity = await self._get_entity(
            entity_type,
            entity_id,
            document_id,
        )
        await self._ensure_entity_source(
            entity_type,
            entity_id,
            document_id,
        )
        running_run = await self._get_running_run(document_id)
        if running_run:
            if (
                getattr(running_run, "scope", "document") == "entity"
                and running_run.target_entity_type == entity_type
                and running_run.target_entity_id == entity_id
            ):
                return running_run, False
            raise EntityExtractionConflictError(
                "当前文档已有其他抽取任务正在执行，请等待完成后重试"
            )

        run = EntityExtractionRun(
            id=uuid.uuid4().hex[:32],
            document_id=document_id,
            status="running",
            scope="entity",
            target_entity_type=entity_type,
            target_entity_id=entity_id,
            extract_knowledge=entity_type == "knowledge_point",
            extract_questions=entity_type == "question",
            subject_id=getattr(entity, "subject_id", None),
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
            run.error_detail = f"单项重提取任务派发失败: {str(exc)[:400]}"
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
                .where(
                    EntityExtractionRun.document_id == document_id,
                    EntityExtractionRun.scope == "document",
                )
                .order_by(EntityExtractionRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def get_latest_entity(
        self,
        document_id: str,
        *,
        entity_type: str,
        entity_id: str,
    ) -> Optional[EntityExtractionRun]:
        await self._get_entity(entity_type, entity_id, document_id)
        return (
            await self.db.execute(
                select(EntityExtractionRun)
                .where(
                    EntityExtractionRun.document_id == document_id,
                    EntityExtractionRun.scope == "entity",
                    EntityExtractionRun.target_entity_type == entity_type,
                    EntityExtractionRun.target_entity_id == entity_id,
                )
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

    async def _get_entity(
        self,
        entity_type: str,
        entity_id: str,
        document_id: str,
    ) -> Any:
        model = {
            "knowledge_point": KnowledgePoint,
            "question": Question,
        }.get(entity_type)
        if not model:
            raise ValueError(f"不支持的实体类型: {entity_type}")
        entity = await self.db.get(model, entity_id)
        if (
            not entity
            or entity.source_document_id != document_id
            or entity.status == "deleted"
        ):
            raise EntityNotFoundError("目标实体不存在或不属于当前文档")
        return entity

    async def _ensure_entity_source(
        self,
        entity_type: str,
        entity_id: str,
        document_id: str,
    ) -> None:
        source = (
            await self.db.execute(
                select(EntitySourceLink)
                .where(
                    EntitySourceLink.entity_type == entity_type,
                    EntitySourceLink.entity_id == entity_id,
                    EntitySourceLink.document_id == document_id,
                )
                .order_by(EntitySourceLink.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not source or not source.block_ids:
            raise EntitySourceUnavailableError(
                "目标实体没有可追溯的来源 block，无法单独重新提取"
            )

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
                await EntityExtractionRunExecutor(session).execute(run_id)
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
            "scope": getattr(run, "scope", "document"),
            "target_entity_type": getattr(
                run,
                "target_entity_type",
                None,
            ),
            "target_entity_id": getattr(run, "target_entity_id", None),
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
