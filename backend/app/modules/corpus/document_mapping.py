"""Document page-to-chapter mapping queries for corpus extraction."""

from typing import Dict, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    CanonicalChapter,
    DocumentSection,
    DocumentSectionMapping,
)
from app.services.chapter_compat_service import resolve_legacy_chapter_id

PageMapping = Dict[str, Optional[str]]
PageMappingIndex = Dict[int, PageMapping]


class DocumentChapterMappingResolver:
    """Load approved section mappings and resolve them for document pages."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def load(self, document_id: str) -> PageMappingIndex:
        """Build a page-indexed mapping from approved document sections."""
        result = await self.db.execute(
            select(DocumentSection, DocumentSectionMapping, CanonicalChapter)
            .join(
                DocumentSectionMapping,
                DocumentSection.id
                == DocumentSectionMapping.document_section_id,
            )
            .join(
                CanonicalChapter,
                DocumentSectionMapping.canonical_chapter_id
                == CanonicalChapter.id,
            )
            .where(
                and_(
                    DocumentSection.document_id == document_id,
                    DocumentSectionMapping.review_status == "approved",
                )
            )
        )

        page_mapping_index: PageMappingIndex = {}
        legacy_chapter_cache: Dict[str, Optional[str]] = {}
        for section, mapping, chapter in result.all():
            if not section.page_start:
                continue
            if chapter.id not in legacy_chapter_cache:
                legacy_chapter_cache[chapter.id] = await resolve_legacy_chapter_id(
                    self.db,
                    canonical_chapter_id=chapter.id,
                    subject_id=chapter.subject_id,
                )
            page_mapping = {
                "chapter_id": mapping.canonical_chapter_id,
                "subject_id": chapter.subject_id,
                "legacy_chapter_id": legacy_chapter_cache[chapter.id],
                "source_section_path": (
                    section.section_path[:500]
                    if section.section_path
                    else None
                ),
            }
            page_end = section.page_end or section.page_start
            for page_no in range(section.page_start, page_end + 1):
                page_mapping_index[page_no] = page_mapping
        return page_mapping_index

    @staticmethod
    def resolve(
        page_no: Optional[int],
        mappings: PageMappingIndex,
    ) -> Optional[PageMapping]:
        """Resolve a page exactly, then from the nearest previous or next page."""
        if page_no is None or not mappings:
            return None
        if page_no in mappings:
            return mappings[page_no]

        previous_pages = [
            mapped_page for mapped_page in mappings if mapped_page <= page_no
        ]
        if previous_pages:
            return mappings[max(previous_pages)]

        next_pages = [
            mapped_page for mapped_page in mappings if mapped_page > page_no
        ]
        if next_pages:
            return mappings[min(next_pages)]
        return None
