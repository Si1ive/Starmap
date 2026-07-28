"""Application service for corpus files and document parse runs."""

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from fastapi import UploadFile
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.mysql import mysql_client
from app.modules.corpus.errors import (
    CorpusFileNotFoundError,
    ParseConflictError,
    ParseRunNotFoundError,
)
from app.modules.corpus.file_service import (
    CorpusFileService,
    SUPPORTED_EXTENSIONS,
)
from app.models.mysql_models import (
    CorpusFile,
    Document,
    DownloadedFile,
    ParseRun,
)
from app.modules.corpus.document_parse_service import DocumentParseService

logger = get_logger(__name__)

UPLOAD_CHUNK_BYTES = 1024 * 1024

_parse_tasks: set[asyncio.Task[Any]] = set()


class CorpusApplicationService:
    """Coordinate corpus persistence, uploads, and asynchronous parsing."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        upload_dir: Optional[Path] = None,
        max_upload_bytes: Optional[int] = None,
    ):
        self.db = db
        self.upload_dir = upload_dir or Path(settings.CORPUS_UPLOAD_DIR)
        self.max_upload_bytes = (
            max_upload_bytes
            if max_upload_bytes is not None
            else settings.CORPUS_UPLOAD_MAX_BYTES
        )

    async def scan_files(
        self,
        *,
        root_path: str,
        file_types: Optional[List[str]],
        batch_label: Optional[str],
    ) -> Dict[str, Any]:
        return await CorpusFileService(self.db).scan_and_register(
            root_path=root_path,
            file_types=file_types,
            batch_label=batch_label,
        )

    async def register_file(
        self,
        *,
        file_path: str,
        batch_label: Optional[str],
    ) -> Dict[str, Any]:
        return await CorpusFileService(self.db).register_single_file(
            file_path=file_path,
            batch_label=batch_label,
        )

    async def register_downloaded_file(
        self,
        *,
        downloaded_file_id: str,
        batch_label: Optional[str],
    ) -> Dict[str, Any]:
        downloaded = await self.db.get(DownloadedFile, downloaded_file_id)
        if not downloaded:
            raise CorpusFileNotFoundError("已下载文件不存在")
        if not downloaded.local_path:
            raise ValueError("该文件未下载到本地，local_path 为空")

        return await CorpusFileService(self.db).register_single_file(
            file_path=downloaded.local_path,
            batch_label=batch_label or downloaded.task_id,
        )

    async def upload_files(
        self,
        files: Sequence[UploadFile],
        *,
        batch_label: Optional[str],
        owner_user_id: object | None = None,
    ) -> Dict[str, Any]:
        if not files:
            raise ValueError("请至少上传一个文件")
        if len(files) > 50:
            raise ValueError("单次最多上传50个文件")

        self.upload_dir.mkdir(parents=True, exist_ok=True)
        batch = batch_label or f"upload-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        success_items: List[Dict[str, Any]] = []
        failed_items: List[Dict[str, Any]] = []
        skipped_items: List[Dict[str, Any]] = []
        corpus_service = CorpusFileService(self.db)

        for upload in files:
            file_result: Dict[str, Any] = {"file_name": upload.filename}
            stored_path: Optional[Path] = None

            try:
                original_name = self._sanitize_upload_name(upload.filename)
                ext = Path(original_name).suffix.lstrip(".").lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
                    raise ValueError(
                        f"不支持的文件类型: {ext}，仅支持 {supported}"
                    )

                stored_path = self.upload_dir / f"{uuid.uuid4().hex}_{original_name}"
                await self._write_upload(upload, stored_path)

                register_kwargs = {
                    "file_path": str(stored_path),
                    "batch_label": batch,
                    "file_name": original_name,
                }
                if owner_user_id is not None:
                    register_kwargs["owner_user_id"] = owner_user_id
                result = await corpus_service.register_single_file(**register_kwargs)
                is_new = result["is_new"]
                file_result.update(
                    {
                        "status": "success" if is_new else "skipped",
                        "corpus_file_id": result["corpus_file_id"],
                        "is_new": is_new,
                    }
                )
                if is_new:
                    success_items.append(file_result)
                else:
                    stored_path.unlink(missing_ok=True)
                    skipped_items.append(file_result)
            except Exception as exc:
                if stored_path:
                    stored_path.unlink(missing_ok=True)
                await self.db.rollback()
                file_result["status"] = "failed"
                file_result["error"] = str(exc)[:200]
                failed_items.append(file_result)
                logger.warning(
                    "文件上传失败",
                    filename=upload.filename,
                    error=str(exc),
                )
            finally:
                await upload.close()

        return {
            "batch_label": batch,
            "total": len(files),
            "success_count": len(success_items),
            "skipped_count": len(skipped_items),
            "failed_count": len(failed_items),
            "success_items": success_items,
            "skipped_items": skipped_items,
            "failed_items": failed_items,
        }

    async def list_files(
        self,
        *,
        page: int,
        page_size: int,
        status: Optional[str],
        source_type: Optional[str],
        file_ext: Optional[str],
        keyword: Optional[str],
    ) -> Dict[str, Any]:
        return await CorpusFileService(self.db).get_corpus_files(
            page=page,
            page_size=page_size,
            status=status,
            source_type=source_type,
            file_ext=file_ext,
            keyword=keyword,
        )

    async def get_file(self, file_id: str) -> Dict[str, Any]:
        result = await CorpusFileService(self.db).get_corpus_file_detail(
            file_id
        )
        if not result:
            raise CorpusFileNotFoundError("语料文件不存在")

        result["parse_runs"] = await DocumentParseService(self.db).get_parse_runs(
            file_id
        )
        return result

    async def get_document(self, document_id: str) -> Dict[str, Any]:
        result = await DocumentParseService(self.db).get_document_detail(document_id)
        if not result:
            raise CorpusFileNotFoundError("文档不存在")
        return result

    async def start_parse(
        self,
        file_id: str,
        *,
        parser_name: Optional[str],
        parse_mode: str,
        auto_extract: bool = False,
    ) -> Dict[str, Any]:
        corpus_file = await self.db.get(
            CorpusFile,
            file_id,
            with_for_update=True,
        )
        if not corpus_file:
            raise CorpusFileNotFoundError("语料文件不存在")
        if corpus_file.status == "parsing":
            raise ParseConflictError("该语料正在解析中，请稍后刷新状态")
        if (
            corpus_file.status in {"parsed", "extracting", "indexed"}
            and parse_mode in {"primary", "fallback"}
        ):
            raise ParseConflictError(
                "该语料已成功解析，如需重跑请使用 retry 或 manual_fix 模式"
            )

        parse_service = DocumentParseService(self.db)
        parser = await parse_service._get_parser(parser_name)
        run_id = parse_service._generate_id()
        parse_run = ParseRun(
            id=run_id,
            corpus_file_id=file_id,
            parser_name=parser.name,
            parser_version=parser.version,
            parse_mode=parse_mode,
            status="running",
            current_stage="parsing",
            stage_detail="准备开始解析...",
        )
        self.db.add(parse_run)
        corpus_file.status = "parsing"
        corpus_file.error_detail = None
        await self.db.commit()

        try:
            schedule_args = (run_id, file_id, parser.name, parse_mode)
            if auto_extract:
                self._schedule_parse(*schedule_args, auto_extract=True)
            else:
                self._schedule_parse(*schedule_args)
        except Exception as exc:
            parse_run.status = "failed"
            parse_run.error_detail = f"解析任务派发失败: {str(exc)[:400]}"
            parse_run.completed_at = datetime.utcnow()
            corpus_file.status = "failed"
            corpus_file.error_detail = parse_run.error_detail
            await self.db.commit()
            raise

        return {
            "run_id": run_id,
            "status": "running",
            "corpus_file_id": file_id,
        }

    async def delete_files(self, file_ids: List[str]) -> Dict[str, Any]:
        unique_ids = list(dict.fromkeys(file_ids))
        result = await self.db.execute(
            select(CorpusFile).where(CorpusFile.id.in_(unique_ids))
        )
        corpus_files = result.scalars().all()
        existing_ids = [item.id for item in corpus_files]
        if not existing_ids:
            raise CorpusFileNotFoundError("未找到可删除的语料文件")

        await self.db.execute(
            delete(ParseRun).where(ParseRun.corpus_file_id.in_(existing_ids))
        )
        await self.db.execute(
            delete(Document).where(Document.corpus_file_id.in_(existing_ids))
        )
        await self.db.execute(
            delete(CorpusFile).where(CorpusFile.id.in_(existing_ids))
        )
        await self.db.commit()

        return {
            "deleted_count": len(corpus_files),
            "requested_count": len(unique_ids),
            "items": [
                {"file_id": item.id, "file_name": item.file_name}
                for item in corpus_files
            ],
        }

    async def list_parse_runs(
        self,
        *,
        corpus_file_id: Optional[str],
        status: Optional[str],
        page: int,
        page_size: int,
    ) -> Dict[str, Any]:
        query = select(ParseRun)
        count_query = select(func.count()).select_from(ParseRun)
        conditions = []
        if corpus_file_id:
            conditions.append(ParseRun.corpus_file_id == corpus_file_id)
        if status:
            conditions.append(ParseRun.status == status)
        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total = await self.db.scalar(count_query) or 0
        result = await self.db.execute(
            query.order_by(ParseRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return {
            "items": [
                self._serialize_parse_run(run)
                for run in result.scalars().all()
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_parse_run(self, run_id: str) -> Dict[str, Any]:
        run = await self.db.get(ParseRun, run_id)
        if not run:
            raise ParseRunNotFoundError("任务不存在")

        document_id = await self.db.scalar(
            select(Document.id)
            .where(Document.corpus_file_id == run.corpus_file_id)
            .limit(1)
        )
        progress = 0
        if run.total_pages and run.total_pages > 0 and run.current_page:
            progress = round((run.current_page / run.total_pages) * 100, 1)

        return {
            **self._serialize_parse_run(run),
            "document_id": document_id,
            "current_stage": run.current_stage,
            "current_page": run.current_page,
            "total_pages": run.total_pages,
            "stage_detail": run.stage_detail,
            "progress": progress,
            "metrics_json": run.metrics_json,
        }

    def _schedule_parse(
        self,
        run_id: str,
        file_id: str,
        parser_name: str,
        parse_mode: str,
        auto_extract: bool = False,
    ) -> None:
        task = asyncio.create_task(
            self._run_parse_in_background(
                run_id,
                file_id,
                parser_name,
                parse_mode,
                auto_extract,
            ),
            name=f"parse-run-{run_id}",
        )
        _parse_tasks.add(task)
        task.add_done_callback(_parse_tasks.discard)

    @staticmethod
    async def _run_parse_in_background(
        run_id: str,
        file_id: str,
        parser_name: str,
        parse_mode: str,
        auto_extract: bool = False,
    ) -> None:
        try:
            async with mysql_client.session() as session:
                result = await DocumentParseService(session).parse_document_with_run_id(
                    run_id=run_id,
                    corpus_file_id=file_id,
                    parser_name=parser_name,
                    parse_mode=parse_mode,
                )
                if auto_extract and result.get("status") == "success":
                    from app.modules.corpus.extraction_tasks import (
                        EntityExtractionTaskService,
                    )

                    await EntityExtractionTaskService(session).start(
                        result["document_id"],
                        extract_knowledge=True,
                        extract_questions=True,
                        subject_id=None,
                    )
        except Exception as exc:
            logger.error(
                "后台解析任务失败",
                run_id=run_id,
                error=str(exc),
            )

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
                        raise ValueError(
                            "文件大小超过限制"
                            f"（最大 {self.max_upload_bytes // (1024 * 1024)} MB）"
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
    def _serialize_parse_run(run: ParseRun) -> Dict[str, Any]:
        return {
            "id": run.id,
            "corpus_file_id": run.corpus_file_id,
            "parser_name": run.parser_name,
            "parser_version": run.parser_version,
            "parse_mode": run.parse_mode,
            "status": run.status,
            "page_count": run.page_count,
            "block_count": run.block_count,
            "asset_count": run.asset_count,
            "confidence": float(run.confidence) if run.confidence else None,
            "error_detail": run.error_detail,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": (
                run.completed_at.isoformat() if run.completed_at else None
            ),
            "created_at": run.created_at.isoformat() if run.created_at else None,
        }
