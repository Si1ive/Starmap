"""Document-native section tree extraction and queries."""

import uuid
from typing import Any, Dict, List

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import Document, DocumentBlock, DocumentSection
from app.modules.corpus.section_heading import (
    build_section_path,
    detect_heading_level,
)

logger = get_logger(__name__)

# 试卷类文档没有原生章节结构（题目直接挂标准章节，不走标题树这一层）
EXAM_DOC_TYPES = {"past_exam", "mock_exam"}


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


class DocumentSectionService:
    """Extract and query the document-native section tree."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def extract_sections(
        self,
        document_id: str,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Extract a hierarchical section tree from normalized document blocks."""
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            raise ValueError(f"文档不存在: {document_id}")

        if document.doc_type in EXAM_DOC_TYPES:
            raise ValueError(
                "试卷类文档没有原生章节结构，题目应直接挂到标准章节上，无需提取标题树"
            )

        existing_sections_result = await self.db.execute(
            select(DocumentSection.id)
            .where(DocumentSection.document_id == document_id)
            .limit(1)
        )
        if existing_sections_result.scalar_one_or_none() and not force:
            raise ValueError("该文档已生成原生标题树，无需重复提取")

        blocks_result = await self.db.execute(
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
        )
        blocks = blocks_result.scalars().all()

        if not blocks:
            logger.warning("文档没有 blocks", document_id=document_id)
            return {"sections_count": 0, "message": "文档没有 blocks"}

        await self.db.execute(
            delete(DocumentSection).where(
                DocumentSection.document_id == document_id
            )
        )

        sections_data: List[Dict[str, Any]] = []
        pending_sections: List[Dict[str, Any]] = []

        for block in blocks:
            text = block.content_text or block.content_md or ""
            level = detect_heading_level(text, block.block_type)
            if level is None:
                continue

            section_data = {
                'id': generate_id(),
                'document_id': document_id,
                'level': level,
                'title': text.strip()[:500],
                'section_path': build_section_path(
                    pending_sections,
                    level,
                    text.strip(),
                )[:1000],
                'page_start': block.page_no,
                'block_start_id': block.id,
                'parent_id': None,
            }

            for index in range(len(pending_sections) - 1, -1, -1):
                if pending_sections[index]['level'] < level:
                    section_data['parent_id'] = pending_sections[index]['id']
                    break

            while (
                pending_sections
                and pending_sections[-1]['level'] >= level
            ):
                closed_section = pending_sections.pop()
                closed_section['page_end'] = block.page_no
                closed_section['block_end_id'] = block.id

            pending_sections.append(section_data)
            sections_data.append(section_data)

        if pending_sections:
            last_block = blocks[-1]
            for section in pending_sections:
                if section.get('page_end') is None:
                    section['page_end'] = last_block.page_no
                    section['block_end_id'] = last_block.id

        for section_data in sections_data:
            self.db.add(
                DocumentSection(
                    id=section_data['id'],
                    document_id=section_data['document_id'],
                    parent_id=section_data.get('parent_id'),
                    level=section_data['level'],
                    title=section_data['title'],
                    section_path=section_data['section_path'],
                    page_start=section_data.get('page_start'),
                    page_end=section_data.get('page_end'),
                    block_start_id=section_data.get('block_start_id'),
                    block_end_id=section_data.get('block_end_id'),
                )
            )

        await self.db.commit()

        logger.info(
            "文档标题树提取完成",
            document_id=document_id,
            sections_count=len(sections_data),
        )

        return {
            "document_id": document_id,
            "sections_count": len(sections_data),
            "sections": [
                {
                    "id": section['id'],
                    "level": section['level'],
                    "title": section['title'],
                    "section_path": section['section_path'],
                    "page_start": section.get('page_start'),
                    "page_end": section.get('page_end'),
                    "parent_id": section.get('parent_id'),
                }
                for section in sections_data
            ],
        }

    async def get_section_tree(
        self,
        document_id: str,
    ) -> List[Dict[str, Any]]:
        """Return document sections as a nested tree."""
        result = await self.db.execute(
            select(DocumentSection)
            .where(DocumentSection.document_id == document_id)
            .order_by(DocumentSection.page_start, DocumentSection.id)
        )
        sections = result.scalars().all()
        if not sections:
            return []

        section_map = {
            section.id: self._section_to_dict(section)
            for section in sections
        }
        root_sections = []

        for section in sections:
            node = section_map[section.id]
            if section.parent_id and section.parent_id in section_map:
                parent = section_map[section.parent_id]
                parent.setdefault('children', []).append(node)
            else:
                root_sections.append(node)

        return root_sections

    async def get_sections_flat(
        self,
        document_id: str,
    ) -> List[Dict[str, Any]]:
        """Return document sections as an ordered flat list."""
        result = await self.db.execute(
            select(DocumentSection)
            .where(DocumentSection.document_id == document_id)
            .order_by(DocumentSection.page_start, DocumentSection.id)
        )
        return [
            self._section_to_dict(section)
            for section in result.scalars().all()
        ]

    def _section_to_dict(
        self,
        section: DocumentSection,
    ) -> Dict[str, Any]:
        return {
            "id": section.id,
            "document_id": section.document_id,
            "parent_id": section.parent_id,
            "level": section.level,
            "title": section.title,
            "section_path": section.section_path,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "block_start_id": section.block_start_id,
            "block_end_id": section.block_end_id,
            "confidence": (
                float(section.confidence)
                if section.confidence
                else None
            ),
            "created_at": (
                section.created_at.isoformat()
                if section.created_at
                else None
            ),
        }
