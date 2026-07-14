"""Chapter ownership diagnostics for document pages and blocks."""

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    CanonicalChapter,
    Document,
    DocumentBlock,
    DocumentPage,
    DocumentSection,
    DocumentSectionMapping,
    EntitySourceLink,
    Subject,
)
from app.modules.catalog.chapter_diagnostics_rules import (
    EXAM_DOC_TYPES,
    block_issues,
    block_text as _block_text,
    build_section_range,
    diagnostic_status,
    looks_like_option_block as _looks_like_option_block,
    looks_like_question_start as _looks_like_question_start,
    mapping_to_dict,
    page_issues,
    resolve_page_mapping,
    section_for_block,
    section_for_page,
    section_to_diag_dict,
    section_with_mapping_to_diag_dict,
    select_mapping_for_section,
    text_excerpt as _text_excerpt,
)


class ChapterOwnershipDiagnosticsService:
    """Inspect page, block, and section chapter ownership without mutating data."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_chapter_ownership_diagnostics(
        self,
        document_id: str,
        page_no: Optional[int] = None,
        include_blocks: bool = True,
    ) -> Dict[str, Any]:
        """
        诊断文档页级/块级章节归属链路。

        这个接口只读当前库内状态，不重建标题树或章节映射。它同时展示：
        - block 所属的原生 section
        - 该 section 自身是否有标准章节映射
        - 实体抽取实际会使用的页级映射（含前后页 fallback）
        """
        document = await self.db.get(Document, document_id)
        if not document:
            raise ValueError(f"文档不存在: {document_id}")

        is_exam_doc = document.doc_type in EXAM_DOC_TYPES

        blocks_query = (
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
        )
        if page_no is not None:
            blocks_query = blocks_query.where(DocumentBlock.page_no == page_no)
        blocks = (await self.db.execute(blocks_query)).scalars().all()

        all_blocks_query = (
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
        )
        all_blocks = (await self.db.execute(all_blocks_query)).scalars().all()
        block_index = {block.id: idx for idx, block in enumerate(all_blocks)}

        sections = (await self.db.execute(
            select(DocumentSection)
            .where(DocumentSection.document_id == document_id)
            .order_by(DocumentSection.page_start, DocumentSection.level, DocumentSection.id)
        )).scalars().all()

        mapping_rows = (await self.db.execute(
            select(DocumentSectionMapping, DocumentSection, CanonicalChapter, Subject)
            .join(DocumentSection, DocumentSectionMapping.document_section_id == DocumentSection.id)
            .join(CanonicalChapter, DocumentSectionMapping.canonical_chapter_id == CanonicalChapter.id)
            .join(Subject, CanonicalChapter.subject_id == Subject.id)
            .where(DocumentSection.document_id == document_id)
            .order_by(DocumentSection.page_start, DocumentSectionMapping.confidence.desc())
        )).all()

        mappings_by_section: Dict[
            str,
            List[Tuple[DocumentSectionMapping, CanonicalChapter, Subject]],
        ] = defaultdict(list)
        for mapping, section, chapter, subject in mapping_rows:
            mappings_by_section[section.id].append((mapping, chapter, subject))

        accepted_page_mappings: Dict[int, Dict[str, Any]] = {}
        for section in sections:
            accepted_mapping = select_mapping_for_section(
                section.id,
                mappings_by_section,
                accepted_only=True,
            )
            if not accepted_mapping or not section.page_start:
                continue
            page_start = section.page_start
            page_end = section.page_end or section.page_start
            for current_page in range(page_start, page_end + 1):
                accepted_page_mappings[current_page] = mapping_to_dict(
                    *accepted_mapping,
                    section=section,
                    source="section_range",
                    fallback_distance=0,
                )

        page_numbers = await self._get_document_page_numbers(
            document_id,
            all_blocks,
            document.page_count,
        )
        if page_no is not None:
            page_numbers = [page for page in page_numbers if page == page_no]

        entity_index = await self._build_entity_source_index(document_id)

        section_ranges = [
            build_section_range(section, block_index, len(all_blocks))
            for section in sections
        ]

        page_items = []
        for current_page in page_numbers:
            page_blocks = [block for block in all_blocks if block.page_no == current_page]
            active_section = section_for_page(current_page, section_ranges)
            raw_section_mapping = (
                select_mapping_for_section(
                    active_section["section"].id,
                    mappings_by_section,
                )
                if active_section
                else None
            )
            section_mapping = None
            if active_section and raw_section_mapping:
                section_mapping = mapping_to_dict(
                    *raw_section_mapping,
                    section=active_section["section"],
                    source="native_section",
                    fallback_distance=0,
                )
            extraction_mapping = resolve_page_mapping(
                current_page,
                accepted_page_mappings,
            )
            page_entities = entity_index["pages"].get(current_page, {})
            current_page_issues = page_issues(
                active_section,
                section_mapping,
                extraction_mapping,
                is_exam_doc,
            )

            page_items.append({
                "page_no": current_page,
                "block_count": len(page_blocks),
                "question_start_count": sum(
                    1 for block in page_blocks
                    if _looks_like_question_start(_block_text(block), block.block_type)
                ),
                "option_block_count": sum(
                    1 for block in page_blocks
                    if _looks_like_option_block(_block_text(block))
                ),
                "native_section": (
                    section_to_diag_dict(active_section["section"])
                    if active_section
                    else None
                ),
                "section_mapping": section_mapping,
                "extraction_mapping": extraction_mapping,
                "diagnostic_status": diagnostic_status(current_page_issues),
                "issues": current_page_issues,
                "extracted": {
                    "knowledge_count": page_entities.get("knowledge_point", 0),
                    "question_count": page_entities.get("question", 0),
                },
            })

        block_items = []
        if include_blocks:
            for block in blocks:
                text = _block_text(block)
                active_section = section_for_block(
                    block,
                    block_index,
                    section_ranges,
                )
                selected_mapping = None
                if active_section:
                    raw_selected = select_mapping_for_section(
                        active_section["section"].id,
                        mappings_by_section,
                    )
                    if raw_selected:
                        selected_mapping = mapping_to_dict(
                            *raw_selected,
                            section=active_section["section"],
                            source="native_section",
                            fallback_distance=0,
                        )

                extraction_mapping = resolve_page_mapping(
                    block.page_no,
                    accepted_page_mappings,
                )
                block_entities = entity_index["blocks"].get(block.id, {})
                current_block_issues = block_issues(
                    active_section,
                    selected_mapping,
                    extraction_mapping,
                    is_exam_doc,
                )

                block_items.append({
                    "id": block.id,
                    "page_no": block.page_no,
                    "order_no": block.order_no,
                    "block_type": block.block_type,
                    "text_excerpt": _text_excerpt(text),
                    "text_length": len(text),
                    "signals": {
                        "looks_like_question_start": _looks_like_question_start(
                            text,
                            block.block_type,
                        ),
                        "looks_like_option": _looks_like_option_block(text),
                        "looks_like_heading": block.block_type in ("title", "heading"),
                    },
                    "native_section": (
                        section_to_diag_dict(active_section["section"])
                        if active_section
                        else None
                    ),
                    "section_mapping": selected_mapping,
                    "extraction_mapping": extraction_mapping,
                    "diagnostic_status": diagnostic_status(
                        current_block_issues
                    ),
                    "issues": current_block_issues,
                    "extracted": {
                        "knowledge_count": block_entities.get("knowledge_point", 0),
                        "question_count": block_entities.get("question", 0),
                    },
                })

        status_counter = Counter(page["diagnostic_status"] for page in page_items)
        block_status_counter = Counter(block["diagnostic_status"] for block in block_items)
        pages_with_questions = [
            page for page in page_items
            if page["question_start_count"] > 0
        ]
        pages_with_question_without_mapping = [
            page for page in pages_with_questions
            if page["diagnostic_status"] != "ok"
        ]

        return {
            "document_id": document.id,
            "document_title": document.title,
            "doc_type": document.doc_type,
            "is_exam_doc": is_exam_doc,
            "page_count": len(page_numbers),
            "block_count": len(blocks),
            "summary": {
                "total_pages": len(page_numbers),
                "total_blocks": len(blocks),
                "total_sections": len(sections),
                "total_mappings": len(mapping_rows),
                "accepted_mappings": sum(
                    1 for mapping, _section, _chapter, _subject in mapping_rows
                    if mapping.review_status in ("approved", "pending")
                ),
                "rejected_mappings": sum(
                    1 for mapping, _section, _chapter, _subject in mapping_rows
                    if mapping.review_status == "rejected"
                ),
                "unmapped_sections": sum(
                    1 for section in sections
                    if not mappings_by_section.get(section.id)
                ),
                "pages_ok": status_counter.get("ok", 0),
                "pages_warning": status_counter.get("warning", 0),
                "pages_error": status_counter.get("error", 0),
                "blocks_ok": block_status_counter.get("ok", 0),
                "blocks_warning": block_status_counter.get("warning", 0),
                "blocks_error": block_status_counter.get("error", 0),
                "question_like_blocks": sum(
                    page["question_start_count"]
                    for page in page_items
                ),
                "question_pages_without_stable_mapping": len(
                    pages_with_question_without_mapping
                ),
                "extracted_knowledge_count": entity_index["entity_totals"].get(
                    "knowledge_point",
                    0,
                ),
                "extracted_question_count": entity_index["entity_totals"].get(
                    "question",
                    0,
                ),
            },
            "pages": page_items,
            "blocks": block_items,
            "sections": [
                section_with_mapping_to_diag_dict(
                    section,
                    mappings_by_section,
                )
                for section in sections
            ],
        }

    async def _get_document_page_numbers(
        self,
        document_id: str,
        blocks: List[DocumentBlock],
        document_page_count: Optional[int],
    ) -> List[int]:
        pages = (await self.db.execute(
            select(DocumentPage.page_no)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_no)
        )).scalars().all()
        if pages:
            return list(pages)
        max_block_page = max((block.page_no for block in blocks), default=0)
        max_page = max(document_page_count or 0, max_block_page)
        return list(range(1, max_page + 1)) if max_page else []

    async def _build_entity_source_index(self, document_id: str) -> Dict[str, Any]:
        links = (await self.db.execute(
            select(EntitySourceLink)
            .where(EntitySourceLink.document_id == document_id)
        )).scalars().all()

        page_counts: Dict[int, Counter] = defaultdict(Counter)
        block_counts: Dict[str, Counter] = defaultdict(Counter)
        entity_totals = Counter()

        for link in links:
            entity_totals[link.entity_type] += 1
            if link.page_start:
                page_end = link.page_end or link.page_start
                for current_page in range(link.page_start, page_end + 1):
                    page_counts[current_page][link.entity_type] += 1
            for block_id in link.block_ids or []:
                block_counts[block_id][link.entity_type] += 1

        return {
            "pages": page_counts,
            "blocks": block_counts,
            "entity_totals": entity_totals,
        }
