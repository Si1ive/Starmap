"""Orchestrate knowledge point grouping and persistence."""

from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.corpus.document_mapping import (
    DocumentChapterMappingResolver,
    PageMappingIndex,
)
from app.modules.corpus.entity_persistence import KnowledgePointPersistence


class KnowledgeExtractionPipeline:
    """Group document blocks into knowledge points and persist them."""

    def __init__(self, db: AsyncSession):
        self.mapping = DocumentChapterMappingResolver(db)
        self.persistence = KnowledgePointPersistence(db)

    async def extract(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[Any],
        section_mappings: PageMappingIndex,
    ) -> int:
        """Save title-led paragraph/list groups as knowledge points."""
        saved_count = 0
        current_title = None
        current_content_blocks: List[Any] = []

        for block in blocks:
            if block.block_type in ("title", "heading"):
                if current_title and current_content_blocks:
                    saved_count += int(
                        await self.save_group(
                            document_id=document_id,
                            fallback_subject_id=fallback_subject_id,
                            title_block=current_title,
                            content_blocks=current_content_blocks,
                            section_mappings=section_mappings,
                        )
                    )
                current_title = block
                current_content_blocks = []
            elif block.block_type in ("paragraph", "list"):
                current_content_blocks.append(block)

        if current_title and current_content_blocks:
            saved_count += int(
                await self.save_group(
                    document_id=document_id,
                    fallback_subject_id=fallback_subject_id,
                    title_block=current_title,
                    content_blocks=current_content_blocks,
                    section_mappings=section_mappings,
                )
            )

        return saved_count

    async def save_group(
        self,
        document_id: str,
        fallback_subject_id: str,
        title_block: Any,
        content_blocks: List[Any],
        section_mappings: PageMappingIndex,
    ) -> bool:
        """Resolve a title page mapping and persist one knowledge point."""
        mapping_info: Optional[Dict[str, Optional[str]]] = (
            self.mapping.resolve(
                getattr(title_block, "page_no", None),
                section_mappings,
            )
        )
        return await self.persistence.save_knowledge_point(
            document_id=document_id,
            fallback_subject_id=fallback_subject_id,
            title_block=title_block,
            content_blocks=content_blocks,
            mapping_info=mapping_info,
        )
