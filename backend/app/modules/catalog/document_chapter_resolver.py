"""通过文档来源 block 和 section 映射解析标准章节。"""

from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    DocumentBlock,
    DocumentSection,
    DocumentSectionMapping,
    EntitySourceLink,
)


class DocumentSectionChapterResolver:
    """Resolve an entity chapter from its approved document section mapping."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve(
        self,
        entity: Any,
        entity_type: str,
    ) -> Optional[Dict[str, Any]]:
        source_link = (
            await self.db.execute(
                select(EntitySourceLink)
                .where(
                    EntitySourceLink.entity_type == entity_type,
                    EntitySourceLink.entity_id == entity.id,
                )
                .order_by(EntitySourceLink.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if not source_link or not source_link.block_ids:
            return None

        block = await self.db.get(DocumentBlock, source_link.block_ids[0])
        if not block:
            return None

        section = (
            await self.db.execute(
                select(DocumentSection)
                .where(
                    DocumentSection.document_id
                    == entity.source_document_id,
                    DocumentSection.page_start <= block.page_no,
                    DocumentSection.page_end >= block.page_no,
                )
                .order_by(DocumentSection.level.desc())
            )
        ).scalar_one_or_none()
        if not section:
            return None

        mapping = (
            await self.db.execute(
                select(DocumentSectionMapping)
                .where(
                    DocumentSectionMapping.document_section_id == section.id,
                    DocumentSectionMapping.review_status == "approved",
                )
                .order_by(DocumentSectionMapping.confidence.desc())
            )
        ).scalar_one_or_none()
        if not mapping:
            return None

        return {
            "chapter_id": mapping.canonical_chapter_id,
            "relevance": float(mapping.confidence),
            "source": "document_mapping",
            "is_primary": True,
            "mapping_type": mapping.mapping_type,
        }
