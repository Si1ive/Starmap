"""大纲文件上传、MinerU 解析和 LLM 拆分任务编排。"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.mysql import mysql_client
from app.models.mysql_models import (
    Document,
    DocumentBlock,
    OutlineIngestionRun,
)
from app.modules.catalog.outline_llm_service import OutlineLLMService
from app.modules.corpus.document_parse_service import (
    DocumentParseService,
    generate_id,
)
from app.modules.corpus.file_service import CorpusFileService

logger = get_logger(__name__)

OUTLINE_PARSER_NAME = "mineru"
OUTLINE_SUPPORTED_EXTENSIONS = {"pdf"}
UPLOAD_CHUNK_BYTES = 1024 * 1024

_outline_parse_tasks: set[asyncio.Task[Any]] = set()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class OutlineParseJob:
    run_id: str
    corpus_file_id: str
    is_new_file: bool
    file_name: str


class OutlineParseRunExecutor:
    """执行一条已持久化的大纲解析任务。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        parse_service: Optional[DocumentParseService] = None,
        llm_service: Optional[OutlineLLMService] = None,
    ):
        self.db = db
        self.parse_service = parse_service or DocumentParseService(db)
        self.llm_service = llm_service or OutlineLLMService(db)

    async def execute(self, job: OutlineParseJob) -> None:
        run = await self.db.get(OutlineIngestionRun, job.run_id)
        if not run:
            logger.error("大纲解析任务不存在", run_id=job.run_id)
            return

        try:
            run.current_stage = "parsing"
            run.stage_detail = "正在使用 MinerU 解析 PDF..."
            await self.db.commit()

            document_id = None
            if not job.is_new_file:
                document_id = await self._find_reusable_document_id(
                    job.corpus_file_id
                )

            if document_id is None:
                parse_result = await self.parse_service.parse_document(
                    job.corpus_file_id,
                    parser_name=OUTLINE_PARSER_NAME,
                    parse_mode=(
                        "primary" if job.is_new_file else "retry"
                    ),
                )
                document_id = parse_result["document_id"]

            run.document_id = document_id
            run.current_stage = "splitting"
            run.stage_detail = "正在用 LLM 拆分大纲..."
            await self.db.commit()

            split = await self.llm_service.split_outline_with_progress(
                job.run_id,
                document_id,
            )
            subjects = split["subjects"]
            successful_subjects = [
                subject for subject in subjects if not subject.get("error")
            ]
            failed_subjects = [
                subject for subject in subjects if subject.get("error")
            ]

            if subjects and len(successful_subjects) == len(subjects):
                run.status = "done"
                run.current_stage = "completed"
                run.stage_detail = f"拆分完成，共 {len(subjects)} 个科目"
                run.error_detail = None
            elif successful_subjects:
                run.status = "partial"
                run.current_stage = "completed"
                run.stage_detail = (
                    "拆分部分完成，"
                    f"成功 {len(successful_subjects)}/{len(subjects)} 个科目"
                )
                run.error_detail = self._format_subject_errors(
                    failed_subjects
                )
            else:
                run.status = "failed"
                run.current_stage = "failed"
                run.stage_detail = (
                    f"拆分失败，0/{len(subjects)} 个科目成功"
                )
                run.error_detail = (
                    self._format_subject_errors(failed_subjects)
                    or "LLM 未产出可用科目"
                )
            run.total_subjects = len(subjects)
            run.processed_subjects = len(subjects)
            run.successful_subjects = len(successful_subjects)
            run.result_summary = {
                **split,
                "file_name": job.file_name,
            }
            run.completed_at = _utcnow()
            await self.db.commit()

            logger.info(
                "大纲解析和拆分完成",
                run_id=job.run_id,
                document_id=document_id,
            )
        except Exception as exc:
            await self._mark_failed(job.run_id, exc)

    async def _find_reusable_document_id(
        self,
        corpus_file_id: str,
    ) -> Optional[str]:
        document = await self.db.scalar(
            select(Document)
            .where(Document.corpus_file_id == corpus_file_id)
            .limit(1)
        )
        if not document:
            return None

        block_count = await self.db.scalar(
            select(func.count())
            .select_from(DocumentBlock)
            .where(DocumentBlock.document_id == document.id)
        )
        if not block_count:
            return None
        return document.id

    @staticmethod
    def _format_subject_errors(
        subjects: list[Dict[str, Any]],
    ) -> Optional[str]:
        details = [
            (
                f"{subject.get('subject_name') or '未命名科目'}："
                f"{subject.get('error')}"
            )
            for subject in subjects
            if subject.get("error")
        ]
        return "；".join(details)[:500] or None

    async def _mark_failed(self, run_id: str, exc: Exception) -> None:
        logger.error(
            "大纲后台任务失败",
            run_id=run_id,
            error=str(exc),
        )
        await self.db.rollback()
        run = await self.db.get(OutlineIngestionRun, run_id)
        if not run:
            return

        run.status = "failed"
        run.current_stage = "failed"
        run.error_detail = str(exc)[:500]
        run.stage_detail = f"失败：{str(exc)[:100]}"
        run.completed_at = _utcnow()
        await self.db.commit()


class OutlineParseTaskService:
    """创建并调度大纲上传解析任务。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        upload_dir: Optional[Path] = None,
        max_upload_bytes: Optional[int] = None,
        corpus_service: Optional[CorpusFileService] = None,
        schedule_job: Optional[Callable[[OutlineParseJob], None]] = None,
    ):
        self.db = db
        self.upload_dir = upload_dir or Path(settings.CORPUS_UPLOAD_DIR)
        self.max_upload_bytes = (
            max_upload_bytes
            if max_upload_bytes is not None
            else settings.CORPUS_UPLOAD_MAX_BYTES
        )
        self.corpus_service = corpus_service or CorpusFileService(db)
        self.schedule_job = schedule_job or self._schedule

    async def start(
        self,
        upload: UploadFile,
        *,
        parser_name: Optional[str],
    ) -> Dict[str, Any]:
        file_path: Optional[Path] = None
        registration: Optional[Dict[str, Any]] = None

        try:
            self._validate_parser_name(parser_name)
            file_name = self._sanitize_upload_name(upload.filename)
            self._validate_extension(file_name)

            self.upload_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            file_path = self.upload_dir / f"{timestamp}_{file_name}"
            await self._write_upload(upload, file_path)
            registration = await self.corpus_service.register_single_file(
                file_path=str(file_path),
                batch_label=f"outline-{timestamp}",
            )

            if not registration["is_new"]:
                file_path.unlink(missing_ok=True)

            run_id = generate_id()
            run = OutlineIngestionRun(
                id=run_id,
                document_id=None,
                outline_name=file_name,
                status="processing",
                current_stage="parsing",
                stage_detail=f"文件已上传：{file_name}",
                started_at=_utcnow(),
            )
            self.db.add(run)
            await self.db.commit()

            job = OutlineParseJob(
                run_id=run_id,
                corpus_file_id=registration["corpus_file_id"],
                is_new_file=registration["is_new"],
                file_name=file_name,
            )
            self.schedule_job(job)
            return {
                "run_id": run_id,
                "corpus_file_id": registration["corpus_file_id"],
                "file_name": file_name,
                "status": "processing",
            }
        except Exception:
            await self.db.rollback()
            if (
                file_path
                and (not registration or not registration.get("is_new"))
            ):
                file_path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

    async def _write_upload(
        self,
        upload: UploadFile,
        destination: Path,
    ) -> None:
        total_bytes = 0
        try:
            with destination.open("wb") as target:
                while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
                    total_bytes += len(chunk)
                    if total_bytes > self.max_upload_bytes:
                        max_mb = self.max_upload_bytes // (1024 * 1024)
                        raise ValueError(
                            f"文件大小超过限制（最大 {max_mb} MB）"
                        )
                    target.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    @staticmethod
    def _sanitize_upload_name(filename: Optional[str]) -> str:
        normalized = (filename or "").replace("\\", "/")
        safe_name = Path(normalized).name.strip()
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("文件名为空")
        return safe_name

    @staticmethod
    def _validate_extension(file_name: str) -> None:
        extension = Path(file_name).suffix.lstrip(".").lower()
        if extension not in OUTLINE_SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(OUTLINE_SUPPORTED_EXTENSIONS))
            raise ValueError(
                f"不支持的文件类型: {extension}，仅支持 {supported}"
            )

    @staticmethod
    def _validate_parser_name(parser_name: Optional[str]) -> None:
        normalized = (parser_name or OUTLINE_PARSER_NAME).strip().lower()
        if normalized != OUTLINE_PARSER_NAME:
            raise ValueError("大纲 PDF 解析器固定使用 MinerU")

    @staticmethod
    def _schedule(job: OutlineParseJob) -> None:
        task = asyncio.create_task(
            OutlineParseTaskService._run_in_background(job),
            name=f"outline-parse-{job.run_id}",
        )
        _outline_parse_tasks.add(task)
        task.add_done_callback(_outline_parse_tasks.discard)

    @staticmethod
    async def _run_in_background(job: OutlineParseJob) -> None:
        try:
            async with mysql_client.session() as session:
                await OutlineParseRunExecutor(session).execute(job)
        except Exception as exc:
            logger.error(
                "大纲后台任务执行器异常退出",
                run_id=job.run_id,
                error=str(exc),
            )
