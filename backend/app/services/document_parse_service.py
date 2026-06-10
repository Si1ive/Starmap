"""
文档解析服务

使用 Docling 解析 PDF/DOCX/PPTX，输出结构化 pages/blocks/assets 并落库。
Phase 0: PoC 验证，输出解析结果概览。
Phase 1: 完整落库 document_pages/document_blocks/document_assets。
"""

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

logger = get_logger(__name__)


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


# Docling block type -> our block_type mapping
BLOCK_TYPE_MAP = {
    "Title": "title",
    "Heading": "heading",
    "Paragraph": "paragraph",
    "ListItem": "list",
    "List": "list",
    "Table": "table",
    "TableCaption": "table_caption",
    "Picture": "figure",
    "Figure": "figure",
    "FigureCaption": "figure_caption",
    "Equation": "formula",
    "CodeBlock": "code",
    "PageBreak": "unknown",
}


def _map_block_type(docling_type: str) -> str:
    """Map Docling block class name to our block_type enum."""
    return BLOCK_TYPE_MAP.get(docling_type, "paragraph")


def _extract_page_no(item) -> int:
    """Extract page number from a Docling block item."""
    # Docling items may have prov (provenance) with page info
    if hasattr(item, "prov") and item.prov:
        prov = item.prov
        if isinstance(prov, list) and len(prov) > 0:
            return getattr(prov[0], "page_no", 1) or 1
        return getattr(prov, "page_no", 1) or 1
    return 1


def _extract_bbox(item) -> Optional[dict]:
    """Extract bounding box from a Docling block item."""
    if hasattr(item, "prov") and item.prov:
        prov = item.prov
        if isinstance(prov, list) and len(prov) > 0:
            prov = prov[0]
        if hasattr(prov, "bbox") and prov.bbox:
            b = prov.bbox
            return {
                "l": getattr(b, "l", None),
                "t": getattr(b, "t", None),
                "r": getattr(b, "r", None),
                "b": getattr(b, "b", None),
            }
    return None


def _extract_text(item) -> str:
    """Extract text content from a Docling block item."""
    if hasattr(item, "text") and item.text:
        return item.text
    if hasattr(item, "caption") and item.caption:
        return item.caption
    return ""


def _extract_md(item) -> str:
    """Extract markdown representation if available."""
    if hasattr(item, "export_to_markdown"):
        try:
            return item.export_to_markdown()
        except Exception:
            pass
    return _extract_text(item)


class DocumentParseService:
    """文档解析服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def parse_document(self, corpus_file_id: str) -> Dict[str, Any]:
        """
        解析单个文档

        1. 读取 corpus_file 记录
        2. 创建 parse_run 记录
        3. 调用 Docling 解析
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

        # 2. 创建 parse_run
        parse_run = ParseRun(
            id=generate_id(),
            corpus_file_id=corpus_file_id,
            parser_name="docling",
            parser_version="2.x",
            parse_mode="primary",
            status="running",
        )
        self.db.add(parse_run)

        # 更新文件状态
        corpus_file.status = "parsing"
        await self.db.commit()

        start_time = time.time()

        try:
            # 3. 调用 Docling 解析
            parse_result = self._run_docling(corpus_file.local_path)

            # 4. 创建/更新 Document
            document = await self._get_or_create_document(
                corpus_file, parse_run.id, parse_result
            )

            # 5. 落库 pages、blocks、assets
            await self._persist_pages(document.id, parse_result["pages"])
            await self._persist_assets(document.id, parse_result["assets"])
            await self._persist_blocks(document.id, parse_result["blocks"])

            elapsed = time.time() - start_time

            # 6. 更新 parse_run
            parse_run.status = "success"
            parse_run.page_count = parse_result.get("page_count", 0)
            parse_run.block_count = parse_result.get("block_count", 0)
            parse_run.asset_count = parse_result.get("asset_count", 0)
            parse_run.completed_at = datetime.utcnow()
            parse_run.metrics_json = {
                "elapsed_seconds": round(elapsed, 2),
                "parser": "docling",
            }

            # 更新文件状态
            corpus_file.status = "parsed"

            # 更新文档
            document.page_count = parse_result.get("page_count", 0)
            document.document_markdown = parse_result.get("document_markdown", "")
            document.status = "pending"

            await self.db.commit()

            logger.info(
                "文档解析成功并落库",
                corpus_file_id=corpus_file_id,
                document_id=document.id,
                pages=parse_result.get("page_count"),
                blocks=parse_result.get("block_count"),
                assets=parse_result.get("asset_count"),
                elapsed=f"{elapsed:.2f}s",
            )

            return {
                "parse_run_id": parse_run.id,
                "document_id": document.id,
                "status": "success",
                "page_count": parse_result.get("page_count", 0),
                "block_count": parse_result.get("block_count", 0),
                "asset_count": parse_result.get("asset_count", 0),
                "elapsed_seconds": round(elapsed, 2),
            }

        except ImportError:
            error_msg = "docling 未安装，请执行: pip install docling>=2.0.0"
            parse_run.status = "failed"
            parse_run.error_detail = error_msg
            corpus_file.status = "failed"
            corpus_file.error_detail = error_msg
            await self.db.commit()
            logger.error("Docling 未安装", corpus_file_id=corpus_file_id)
            raise RuntimeError(error_msg)

        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = str(e)[:500]
            parse_run.status = "failed"
            parse_run.error_detail = error_msg
            parse_run.completed_at = datetime.utcnow()
            parse_run.metrics_json = {"elapsed_seconds": round(elapsed, 2)}

            corpus_file.status = "failed"
            corpus_file.error_detail = error_msg

            await self.db.commit()
            logger.error("文档解析失败", corpus_file_id=corpus_file_id, error=error_msg)
            raise

    def _run_docling(self, file_path: str) -> Dict[str, Any]:
        """
        调用 Docling 解析文档

        Returns:
            dict with keys: page_count, block_count, asset_count,
                            pages, blocks, assets, document_markdown
        """
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(file_path)
        doc = result.document

        # --- pages ---
        pages_raw = doc.pages if hasattr(doc, "pages") else []
        pages = []
        for i, page in enumerate(pages_raw):
            page_no = i + 1
            width = getattr(page, "width", None) or getattr(page, "size", None)
            height = getattr(page, "height", None)
            if hasattr(page, "size") and page.size:
                width = getattr(page.size, "width", width)
                height = getattr(page.size, "height", height)
            pages.append({
                "page_no": page_no,
                "width": int(width) if width else None,
                "height": int(height) if height else None,
            })

        # --- blocks ---
        blocks = []
        block_count = 0
        order_counters: Dict[int, int] = {}  # page_no -> order_no counter

        if hasattr(doc, "body") and doc.body:
            for item in doc.body.walk():
                block_count += 1
                docling_type = type(item).__name__
                block_type = _map_block_type(docling_type)
                page_no = _extract_page_no(item)

                # Increment per-page order
                order_no = order_counters.get(page_no, 0)
                order_counters[page_no] = order_no + 1

                text = _extract_text(item)
                md = _extract_md(item)

                block_data = {
                    "page_no": page_no,
                    "block_type": block_type,
                    "order_no": order_no,
                    "content_text": text,
                    "content_md": md if md != text else None,
                    "bbox": _extract_bbox(item),
                }

                # Extract table HTML if it's a table
                if docling_type in ("Table",) and hasattr(item, "export_to_html"):
                    try:
                        block_data["html_table"] = item.export_to_html()
                    except Exception:
                        pass

                # Extract LaTeX for equations
                if docling_type in ("Equation",) and hasattr(item, "text"):
                    block_data["latex"] = getattr(item, "text", None)

                blocks.append(block_data)

        # --- assets (figures/pictures) ---
        assets = []
        asset_count = 0
        if hasattr(doc, "pictures"):
            for pic in doc.pictures:
                asset_count += 1
                page_no = 1
                caption = ""
                if hasattr(pic, "prov") and pic.prov:
                    prov = pic.prov[0] if isinstance(pic.prov, list) and pic.prov else pic.prov
                    page_no = getattr(prov, "page_no", 1) or 1
                if hasattr(pic, "caption"):
                    caption = pic.caption or ""
                elif hasattr(pic, "text"):
                    caption = pic.text or ""

                assets.append({
                    "page_no": page_no,
                    "asset_type": "figure",
                    "caption_text": caption,
                    "bbox": _extract_bbox(pic),
                })

        # --- document markdown ---
        document_markdown = ""
        if hasattr(doc, "export_to_markdown"):
            try:
                document_markdown = doc.export_to_markdown()
            except Exception:
                pass

        return {
            "page_count": len(pages),
            "block_count": block_count,
            "asset_count": asset_count,
            "pages": pages,
            "blocks": blocks,
            "assets": assets,
            "document_markdown": document_markdown,
        }

    async def _get_or_create_document(
        self,
        corpus_file: CorpusFile,
        parse_run_id: str,
        parse_result: Dict[str, Any],
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

    async def _persist_pages(self, document_id: str, pages: List[Dict[str, Any]]) -> None:
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
                page_no=page_data["page_no"],
                width=page_data.get("width"),
                height=page_data.get("height"),
            )
            self.db.add(page)

        await self.db.flush()

    async def _persist_assets(self, document_id: str, assets: List[Dict[str, Any]]) -> None:
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
                page_no=asset_data["page_no"],
                asset_type=asset_data.get("asset_type", "figure"),
                file_path="",  # Phase 2: save actual file
                caption_text=asset_data.get("caption_text"),
                bbox=asset_data.get("bbox"),
            )
            self.db.add(asset)

        await self.db.flush()

    async def _persist_blocks(self, document_id: str, blocks: List[Dict[str, Any]]) -> None:
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
                page_no=block_data["page_no"],
                block_type=block_data["block_type"],
                order_no=block_data["order_no"],
                content_text=block_data.get("content_text"),
                content_md=block_data.get("content_md"),
                bbox=block_data.get("bbox"),
                html_table=block_data.get("html_table"),
                latex=block_data.get("latex"),
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
            "status": document.status,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
            "pages": pages,
            "blocks": blocks,
            "assets": assets,
        }
