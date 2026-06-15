"""
文档解析服务

通过标准化适配层解析 PDF/DOCX/PPTX，输出统一的 pages/blocks/assets 并落库。
当前支持 Docling / MinerU 双解析器，可手动切换单一活动解析器。
"""

import asyncio
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    CorpusFile, ParseRun, Document,
    DocumentPage, DocumentBlock, DocumentAsset,
)
from app.services.document_parsers import (
    ParserUnavailableError,
    ParsedAsset,
    ParsedBlock,
    ParsedDocumentResult,
    ParsedPage,
    choose_parser,
)
from app.services.system_settings_service import SystemSettingsService

logger = get_logger(__name__)


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


class DocumentParseService:
    """文档解析服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def parse_document(
        self,
        corpus_file_id: str,
        parser_name: Optional[str] = None,
        parse_mode: str = "primary",
    ) -> Dict[str, Any]:
        """
        解析单个文档

        1. 读取 corpus_file 记录
        2. 创建 parse_run 记录
        3. 选择解析器并输出标准化结构
        4. 创建/更新 Document 记录
        5. 落库 pages、blocks、assets
        6. 更新 parse_run 状态和指标
        """
        # 1. 获取文件记录
        result = await self.db.execute(
            select(CorpusFile).where(CorpusFile.id == corpus_file_id)
        )
        corpus_file = result.scalar_one_or_none()
        if not corpus_file:
            raise ValueError(f"语料文件不存在: {corpus_file_id}")

        if not corpus_file.local_path or not Path(corpus_file.local_path).exists():
            raise ValueError(f"文件不存在于磁盘: {corpus_file.local_path}")

        if corpus_file.status == "parsing":
            raise ValueError("该语料正在解析中，请稍后刷新状态")

        if corpus_file.status == "parsed" and parse_mode in {"primary", "fallback"}:
            existing_document = await self._get_document_by_corpus_file_id(corpus_file_id)
            raise ValueError(
                "该语料已成功解析，无需重复执行；如需重跑请使用 retry 或 manual_fix 模式"
                if existing_document
                else "该语料已标记为解析成功，无需重复执行；如需重跑请使用 retry 或 manual_fix 模式"
            )

        runtime_config = await SystemSettingsService(self.db).get_pdf_parser_runtime_config()
        parser = choose_parser(
            requested_parser=parser_name,
            runtime_config=runtime_config,
        )

        # 2. 创建 parse_run
        parse_run = ParseRun(
            id=generate_id(),
            corpus_file_id=corpus_file_id,
            parser_name=parser.name,
            parser_version=parser.version,
            parse_mode=parse_mode,
            status="running",
        )
        self.db.add(parse_run)

        # 更新文件状态
        corpus_file.status = "parsing"
        corpus_file.error_detail = None
        await self.db.commit()

        start_time = time.time()

        try:
            # 3. 调用解析器并标准化
            # 解析器本身是同步 CPU/IO 重任务，放到线程池执行，避免阻塞事件循环，
            # 否则解析过程中管理端的列表查询会一起超时。
            parse_result = await asyncio.to_thread(parser.parse, corpus_file.local_path)

            # 4. 创建/更新 Document
            document = await self._get_or_create_document(
                corpus_file, parse_run.id, parse_result
            )

            # 5. 落库 pages、blocks、assets
            await self._persist_pages(document.id, parse_result.pages)
            await self._persist_assets(document.id, parse_result.assets)
            await self._persist_blocks(document.id, parse_result.blocks)

            elapsed = time.time() - start_time

            # 6. 更新 parse_run
            parse_run.status = "success"
            parse_run.parser_name = parse_result.parser_name
            parse_run.parser_version = parse_result.parser_version
            parse_run.parse_mode = parse_mode
            parse_run.page_count = parse_result.page_count
            parse_run.block_count = parse_result.block_count
            parse_run.asset_count = parse_result.asset_count
            parse_run.confidence = parse_result.confidence
            parse_run.completed_at = datetime.utcnow()
            parse_run.metrics_json = {
                "elapsed_seconds": round(elapsed, 2),
                "parser": parse_result.parser_name,
                "parser_version": parse_result.parser_version,
                "parse_mode": parse_mode,
                "metadata": parse_result.metadata or {},
            }

            # 更新文件状态
            corpus_file.status = "parsed"
            corpus_file.error_detail = None

            # 更新文档
            document.page_count = parse_result.page_count
            document.document_markdown = parse_result.document_markdown or ""
            document.document_json = self._serialize_parse_result(parse_result)
            document.status = "pending"

            await self.db.commit()

            logger.info(
                "文档解析成功并落库",
                corpus_file_id=corpus_file_id,
                document_id=document.id,
                parser=parse_result.parser_name,
                parse_mode=parse_mode,
                pages=parse_result.page_count,
                blocks=parse_result.block_count,
                assets=parse_result.asset_count,
                elapsed=f"{elapsed:.2f}s",
            )

            return {
                "parse_run_id": parse_run.id,
                "document_id": document.id,
                "status": "success",
                "parser_name": parse_result.parser_name,
                "parser_version": parse_result.parser_version,
                "parse_mode": parse_mode,
                "page_count": parse_result.page_count,
                "block_count": parse_result.block_count,
                "asset_count": parse_result.asset_count,
                "elapsed_seconds": round(elapsed, 2),
            }

        except ParserUnavailableError as e:
            elapsed = time.time() - start_time
            error_msg = (
                f"当前激活解析器 {parser.name} 不可用：{str(e)}。"
                " 请在系统设置 -> PDF解析器完成停旧启新后重试。"
            )[:500]
            parse_run.status = "failed"
            parse_run.error_detail = error_msg
            parse_run.completed_at = datetime.utcnow()
            parse_run.metrics_json = {
                "elapsed_seconds": round(elapsed, 2),
                "parser": parser.name,
                "parser_version": parser.version,
                "parse_mode": parse_mode,
            }
            corpus_file.status = "failed"
            corpus_file.error_detail = error_msg
            await self.db.commit()
            logger.error(
                "文档解析器不可用",
                corpus_file_id=corpus_file_id,
                parser=parser.name,
                error=error_msg,
            )
            raise ParserUnavailableError(parser.name, error_msg) from e

        except RuntimeError as e:
            elapsed = time.time() - start_time
            error_msg = str(e)[:500]
            parse_run.status = "failed"
            parse_run.error_detail = error_msg
            parse_run.completed_at = datetime.utcnow()
            parse_run.metrics_json = {
                "elapsed_seconds": round(elapsed, 2),
                "parser": parser.name,
                "parser_version": parser.version,
                "parse_mode": parse_mode,
            }
            corpus_file.status = "failed"
            corpus_file.error_detail = error_msg
            await self.db.commit()
            logger.error(
                "文档解析运行时失败",
                corpus_file_id=corpus_file_id,
                parser=parser.name,
                error=error_msg,
            )
            raise

        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = str(e)[:500]
            parse_run.status = "failed"
            parse_run.error_detail = error_msg
            parse_run.completed_at = datetime.utcnow()
            parse_run.metrics_json = {
                "elapsed_seconds": round(elapsed, 2),
                "parser": parser.name,
                "parser_version": parser.version,
                "parse_mode": parse_mode,
            }

            corpus_file.status = "failed"
            corpus_file.error_detail = error_msg

            await self.db.commit()
            logger.error(
                "文档解析失败",
                corpus_file_id=corpus_file_id,
                parser=parser.name,
                error=error_msg,
            )
            raise

    async def _get_document_by_corpus_file_id(self, corpus_file_id: str) -> Optional[Document]:
        result = await self.db.execute(
            select(Document).where(Document.corpus_file_id == corpus_file_id)
        )
        return result.scalar_one_or_none()

    async def _get_or_create_document(
        self,
        corpus_file: CorpusFile,
        parse_run_id: str,
        parse_result: ParsedDocumentResult,
    ) -> Document:
        """Get existing or create new Document for a corpus file."""
        result = await self.db.execute(
            select(Document).where(Document.corpus_file_id == corpus_file.id)
        )
        document = result.scalar_one_or_none()

        if not document:
            document = Document(
                id=generate_id(),
                corpus_file_id=corpus_file.id,
                title=corpus_file.file_name,
                doc_type=corpus_file.doc_type,
                language=corpus_file.language,
                status="pending",
            )
            self.db.add(document)

        document.latest_parse_run_id = parse_run_id
        await self.db.flush()
        return document

    def _serialize_parse_result(self, parse_result: ParsedDocumentResult) -> Dict[str, Any]:
        return {
            "parser_name": parse_result.parser_name,
            "parser_version": parse_result.parser_version,
            "confidence": parse_result.confidence,
            "metadata": parse_result.metadata or {},
            "page_count": parse_result.page_count,
            "block_count": parse_result.block_count,
            "asset_count": parse_result.asset_count,
            "pages": [
                {
                    "page_no": page.page_no,
                    "width": page.width,
                    "height": page.height,
                }
                for page in parse_result.pages
            ],
            "blocks": [
                {
                    "page_no": block.page_no,
                    "block_type": block.block_type,
                    "order_no": block.order_no,
                    "content_text": block.content_text,
                    "content_md": block.content_md,
                    "bbox": block.bbox,
                    "html_table": block.html_table,
                    "latex": block.latex,
                }
                for block in parse_result.blocks
            ],
            "assets": [
                {
                    "page_no": asset.page_no,
                    "asset_type": asset.asset_type,
                    "caption_text": asset.caption_text,
                    "bbox": asset.bbox,
                    "file_path": asset.file_path,
                }
                for asset in parse_result.assets
            ],
        }

    async def _persist_pages(self, document_id: str, pages: List[ParsedPage]) -> None:
        """Persist page records."""
        # Remove old pages for re-parse
        old = await self.db.execute(
            select(DocumentPage).where(DocumentPage.document_id == document_id)
        )
        for p in old.scalars().all():
            await self.db.delete(p)

        for page_data in pages:
            page = DocumentPage(
                id=generate_id(),
                document_id=document_id,
                page_no=page_data.page_no,
                width=page_data.width,
                height=page_data.height,
            )
            self.db.add(page)

        await self.db.flush()

    async def _persist_assets(self, document_id: str, assets: List[ParsedAsset]) -> None:
        """Persist asset records."""
        # Remove old assets for re-parse
        old = await self.db.execute(
            select(DocumentAsset).where(DocumentAsset.document_id == document_id)
        )
        for a in old.scalars().all():
            await self.db.delete(a)

        for asset_data in assets:
            asset = DocumentAsset(
                id=generate_id(),
                document_id=document_id,
                page_no=asset_data.page_no,
                asset_type=asset_data.asset_type or "figure",
                file_path=asset_data.file_path or "",
                caption_text=asset_data.caption_text,
                bbox=asset_data.bbox,
            )
            self.db.add(asset)

        await self.db.flush()

    async def _persist_blocks(self, document_id: str, blocks: List[ParsedBlock]) -> None:
        """Persist block records."""
        # Remove old blocks for re-parse
        old = await self.db.execute(
            select(DocumentBlock).where(DocumentBlock.document_id == document_id)
        )
        for b in old.scalars().all():
            await self.db.delete(b)

        for block_data in blocks:
            block = DocumentBlock(
                id=generate_id(),
                document_id=document_id,
                page_no=block_data.page_no,
                block_type=block_data.block_type,
                order_no=block_data.order_no,
                content_text=block_data.content_text,
                content_md=block_data.content_md,
                bbox=block_data.bbox,
                html_table=block_data.html_table,
                latex=block_data.latex,
            )
            self.db.add(block)

        await self.db.flush()

    async def get_parse_runs(self, corpus_file_id: str) -> List[Dict[str, Any]]:
        """获取文件的所有解析记录"""
        result = await self.db.execute(
            select(ParseRun)
            .where(ParseRun.corpus_file_id == corpus_file_id)
            .order_by(ParseRun.created_at.desc())
        )
        runs = result.scalars().all()
        return [
            {
                "id": r.id,
                "parser_name": r.parser_name,
                "parser_version": r.parser_version,
                "parse_mode": r.parse_mode,
                "status": r.status,
                "page_count": r.page_count,
                "block_count": r.block_count,
                "asset_count": r.asset_count,
                "confidence": float(r.confidence) if r.confidence else None,
                "error_detail": r.error_detail,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in runs
        ]

    async def get_document_detail(self, document_id: str) -> Optional[Dict[str, Any]]:
        """获取文档详情（含 pages 和 blocks）"""
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            return None

        # pages
        pages_result = await self.db.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_no)
        )
        pages = [
            {
                "id": p.id,
                "page_no": p.page_no,
                "width": p.width,
                "height": p.height,
            }
            for p in pages_result.scalars().all()
        ]

        # blocks
        blocks_result = await self.db.execute(
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
        )
        blocks = [
            {
                "id": b.id,
                "page_no": b.page_no,
                "block_type": b.block_type,
                "order_no": b.order_no,
                "content_text": b.content_text,
                "content_md": b.content_md,
                "html_table": b.html_table,
                "latex": b.latex,
                "bbox": b.bbox,
                "review_status": b.review_status,
            }
            for b in blocks_result.scalars().all()
        ]

        # assets
        assets_result = await self.db.execute(
            select(DocumentAsset)
            .where(DocumentAsset.document_id == document_id)
            .order_by(DocumentAsset.page_no)
        )
        assets = [
            {
                "id": a.id,
                "page_no": a.page_no,
                "asset_type": a.asset_type,
                "caption_text": a.caption_text,
                "file_path": a.file_path,
            }
            for a in assets_result.scalars().all()
        ]

        return {
            "id": document.id,
            "corpus_file_id": document.corpus_file_id,
            "title": document.title,
            "doc_type": document.doc_type,
            "subject_id": document.subject_id,
            "source_label": document.source_label,
            "page_count": document.page_count,
            "latest_parse_run_id": document.latest_parse_run_id,
            "document_markdown": document.document_markdown,
            "document_json": document.document_json,
            "status": document.status,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
            "pages": pages,
            "blocks": blocks,
            "assets": assets,
        }
