"""Document analysis workflows for the corpus module."""

import asyncio
import base64
import io
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CorpusFile, DocumentBlock
from app.modules.corpus.content_overview import CorpusContentOverviewService
from app.modules.corpus.errors import (
    DocumentNotFoundError,
    DocumentPageNotFoundError,
    PageRenderError,
    SourceFileNotFoundError,
)
from app.modules.catalog.chapter_diagnostics_service import (
    ChapterOwnershipDiagnosticsService,
)
from app.modules.catalog.chapter_mapping_service import ChapterMappingService
from app.services.document_parse_service import DocumentParseService
from app.services.document_section_service import DocumentSectionService

logger = get_logger(__name__)


class CorpusDocumentService:
    """Coordinate normalized document inspection and chapter workflows."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_blocks(
        self,
        document_id: str,
        *,
        page_no: Optional[int],
        block_type: Optional[str],
        review_status: Optional[str],
        page: int,
        page_size: int,
    ) -> Dict[str, Any]:
        query = select(DocumentBlock).where(
            DocumentBlock.document_id == document_id
        )
        count_query = (
            select(func.count())
            .select_from(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
        )

        conditions = []
        if page_no is not None:
            conditions.append(DocumentBlock.page_no == page_no)
        if block_type:
            conditions.append(DocumentBlock.block_type == block_type)
        if review_status:
            conditions.append(DocumentBlock.review_status == review_status)
        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total = await self.db.scalar(count_query) or 0
        result = await self.db.execute(
            query.order_by(DocumentBlock.page_no, DocumentBlock.order_no)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return {
            "items": [
                self._serialize_block(block)
                for block in result.scalars().all()
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_sections(
        self,
        document_id: str,
        *,
        tree: bool,
    ) -> Any:
        service = DocumentSectionService(self.db)
        if tree:
            return await service.get_section_tree(document_id)
        return await service.get_sections_flat(document_id)

    async def get_page_analysis(
        self,
        document_id: str,
        *,
        page_no: int,
    ) -> Dict[str, Any]:
        document = await DocumentParseService(self.db).get_document_detail(
            document_id
        )
        if not document:
            raise DocumentNotFoundError("文档不存在")

        corpus_file = await self.db.get(
            CorpusFile,
            document["corpus_file_id"],
        )
        if not corpus_file or not corpus_file.local_path:
            raise SourceFileNotFoundError("原始文件不存在")

        source_path = Path(corpus_file.local_path)
        if not source_path.exists():
            raise SourceFileNotFoundError("PDF文件不存在于磁盘")

        try:
            page_image_base64 = await asyncio.to_thread(
                self._render_pdf_page,
                source_path,
                page_no,
            )
        except DocumentPageNotFoundError:
            raise
        except Exception as exc:
            logger.error(
                "PDF渲染失败",
                document_id=document_id,
                page_no=page_no,
                error=str(exc),
            )
            raise PageRenderError(f"PDF渲染失败: {str(exc)[:200]}") from exc

        raw_parse_data, parser_name = self.extract_raw_page_data(
            document.get("raw_parser_output"),
            page_no,
        )
        return {
            "document_id": document_id,
            "page_no": page_no,
            "page_image": f"data:image/png;base64,{page_image_base64}",
            "page_info": next(
                (
                    item
                    for item in document.get("pages", [])
                    if item["page_no"] == page_no
                ),
                None,
            ),
            "blocks": [
                item
                for item in document.get("blocks", [])
                if item["page_no"] == page_no
            ],
            "assets": [
                item
                for item in document.get("assets", [])
                if item["page_no"] == page_no
            ],
            "raw_parse_data": raw_parse_data,
            "parser_name": parser_name,
        }

    async def extract_sections(
        self,
        document_id: str,
        *,
        force: bool,
    ) -> Dict[str, Any]:
        return await DocumentSectionService(self.db).extract_sections(
            document_id,
            force=force,
        )

    async def map_chapters(
        self,
        document_id: str,
        *,
        subject_id: Optional[str],
        outline_id: Optional[str],
        auto_approve_threshold: float,
        force: bool,
    ) -> Dict[str, Any]:
        return await ChapterMappingService(self.db).map_sections(
            document_id=document_id,
            subject_id=subject_id,
            outline_id=outline_id,
            auto_approve_threshold=auto_approve_threshold,
            force=force,
        )

    async def get_section_mappings(
        self,
        document_id: str,
        *,
        review_status: Optional[str],
    ) -> Any:
        return await ChapterMappingService(self.db).get_section_mappings(
            document_id,
            review_status,
        )

    async def get_chapter_diagnostics(
        self,
        document_id: str,
        *,
        page_no: Optional[int],
        include_blocks: bool,
    ) -> Dict[str, Any]:
        return await ChapterOwnershipDiagnosticsService(
            self.db
        ).get_chapter_ownership_diagnostics(
            document_id=document_id,
            page_no=page_no,
            include_blocks=include_blocks,
        )

    async def get_content_overview(
        self,
        document_id: str,
    ) -> Dict[str, Any]:
        result = await CorpusContentOverviewService(self.db).get(document_id)
        if not result:
            raise DocumentNotFoundError("文档不存在")
        return result

    @staticmethod
    def extract_raw_page_data(
        raw_output: Any,
        page_no: int,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if not isinstance(raw_output, dict):
            return None, None

        parser_name = raw_output.get("parser") or raw_output.get("parser_name")
        content_list = raw_output.get("content_list")
        if isinstance(content_list, list):
            page_items = [
                item
                for item in content_list
                if isinstance(item, dict)
                and CorpusDocumentService._raw_item_page(item) == page_no
            ]
            return {
                "parser": parser_name,
                "content_list": page_items,
            }, parser_name

        blocks = raw_output.get("blocks")
        if isinstance(blocks, list):
            assets = raw_output.get("assets")
            return {
                "parser": parser_name,
                "blocks": [
                    item
                    for item in blocks
                    if isinstance(item, dict)
                    and CorpusDocumentService._coerce_page_no(
                        item.get("page_no")
                    )
                    == page_no
                ],
                "assets": [
                    item
                    for item in assets or []
                    if isinstance(item, dict)
                    and CorpusDocumentService._coerce_page_no(
                        item.get("page_no")
                    )
                    == page_no
                ],
            }, parser_name

        if "metadata" in raw_output:
            return raw_output, parser_name
        return None, parser_name

    @staticmethod
    def _render_pdf_page(source_path: Path, page_no: int) -> str:
        from pdf2image import convert_from_path

        images = convert_from_path(
            str(source_path),
            first_page=page_no,
            last_page=page_no,
            dpi=150,
        )
        if not images:
            raise DocumentPageNotFoundError(f"无法提取第{page_no}页")

        image_bytes = io.BytesIO()
        images[0].save(image_bytes, format="PNG", optimize=True)
        return base64.b64encode(image_bytes.getvalue()).decode("utf-8")

    @staticmethod
    def _raw_item_page(item: Dict[str, Any]) -> Optional[int]:
        if item.get("page_idx") is not None:
            page_idx = CorpusDocumentService._coerce_page_no(
                item.get("page_idx")
            )
            return page_idx + 1 if page_idx is not None else None
        return CorpusDocumentService._coerce_page_no(item.get("page_no", 1))

    @staticmethod
    def _coerce_page_no(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _serialize_block(block: DocumentBlock) -> Dict[str, Any]:
        return {
            "id": block.id,
            "document_id": block.document_id,
            "page_id": block.page_id,
            "page_no": block.page_no,
            "block_type": block.block_type,
            "order_no": block.order_no,
            "content_text": block.content_text,
            "content_md": block.content_md,
            "html_table": block.html_table,
            "latex": block.latex,
            "bbox": block.bbox,
            "confidence": (
                float(block.confidence)
                if block.confidence is not None
                else None
            ),
            "review_status": block.review_status,
            "created_at": (
                block.created_at.isoformat() if block.created_at else None
            ),
        }
