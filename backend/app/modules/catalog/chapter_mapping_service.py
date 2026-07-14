"""Document section mapping and review workflows."""

import uuid
from typing import Dict, Any, List, Optional

from sqlalchemy import select, and_, or_, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    CanonicalChapter, DocumentSection, DocumentSectionMapping,
    Document,
)
from app.modules.catalog.chapter_diagnostics_service import (
    EXAM_DOC_TYPES,
    ChapterOwnershipDiagnosticsService,
)

logger = get_logger(__name__)


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


class ChapterMappingService:
    """章节映射服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.diagnostics = ChapterOwnershipDiagnosticsService(db)

    async def map_sections(
        self,
        document_id: str,
        subject_id: Optional[str] = None,
        outline_id: Optional[str] = None,
        auto_approve_threshold: float = 0.90,
        reject_threshold: float = 0.60,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        将文档的 sections 映射到标准章节

        subject_id 可选：传入时只匹配该学科的标准章节，不传则遍历所有学科
        outline_id 可选：传入时只匹配该大纲下的章节（精度最高）

        Returns:
            映射结果统计
        """
        document = await self.db.get(Document, document_id)
        if not document:
            raise ValueError(f"文档不存在: {document_id}")
        if document.doc_type in EXAM_DOC_TYPES:
            raise ValueError(
                "试卷类文档没有标题树，章节映射不适用；试卷题目应在抽取时直接挂到标准章节"
            )

        # 1. 获取文档的 sections
        sections_result = await self.db.execute(
            select(DocumentSection)
            .where(DocumentSection.document_id == document_id)
            .order_by(DocumentSection.page_start)
        )
        sections = sections_result.scalars().all()

        if not sections:
            return {"mapped_count": 0, "message": "文档没有 sections"}

        existing_mapping_result = await self.db.execute(
            select(DocumentSectionMapping.id)
            .join(DocumentSection, DocumentSectionMapping.document_section_id == DocumentSection.id)
            .where(DocumentSection.document_id == document_id)
            .limit(1)
        )
        if existing_mapping_result.scalar_one_or_none() and not force:
            raise ValueError("该文档已完成章节映射，无需重复执行")
        if force:
            await self.db.execute(
                delete(DocumentSectionMapping).where(
                    DocumentSectionMapping.document_section_id.in_([section.id for section in sections])
                )
            )

        # 2. 获取标准章节 — 按 outline / subject / 全量
        if outline_id:
            chapters_result = await self.db.execute(
                select(CanonicalChapter)
                .where(CanonicalChapter.outline_id == outline_id)
                .where(CanonicalChapter.status == "active")
                .order_by(CanonicalChapter.subject_id, CanonicalChapter.sort_order)
            )
            outline_chapters = chapters_result.scalars().all()
            chapter_groups: Dict[str, list] = {}
            for ch in outline_chapters:
                chapter_groups.setdefault(ch.subject_id, []).append(ch)
        elif subject_id:
            chapters_result = await self.db.execute(
                select(CanonicalChapter)
                .where(CanonicalChapter.subject_id == subject_id)
                .order_by(CanonicalChapter.sort_order)
            )
            chapter_groups = {subject_id: chapters_result.scalars().all()}
        else:
            chapters_result = await self.db.execute(
                select(CanonicalChapter)
                .where(CanonicalChapter.status == "active")
                .order_by(CanonicalChapter.subject_id, CanonicalChapter.sort_order)
            )
            all_chapters = chapters_result.scalars().all()
            chapter_groups: Dict[str, list] = {}
            for ch in all_chapters:
                chapter_groups.setdefault(ch.subject_id, []).append(ch)
        # 3. 构建匹配索引 — 每个学科一个索引
        chapter_indices: Dict[str, Dict[str, Any]] = {}
        for sid, chapters in chapter_groups.items():
            if chapters:
                chapter_indices[sid] = self._build_chapter_index(chapters)

        # 4. 逐个 section 进行映射，跨学科取最佳匹配
        mapped_count = 0
        auto_approved = 0
        pending_review = 0
        rejected = 0

        for section in sections:
            match_result = self._match_section_multi(section, chapter_indices)

            if match_result:
                chapter_id, confidence, mapping_type = match_result

                # Section 映射只作为内部辅助，不再产生独立审核项。
                # 低置信匹配交给实体抽取阶段的章节直接解析兜底。
                if confidence >= auto_approve_threshold:
                    review_status = "approved"
                    auto_approved += 1
                else:
                    review_status = "rejected"
                    rejected += 1

                mapping = DocumentSectionMapping(
                    id=generate_id(),
                    document_section_id=section.id,
                    canonical_chapter_id=chapter_id,
                    mapping_type=mapping_type,
                    confidence=confidence,
                    review_status=review_status,
                )
                self.db.add(mapping)
                mapped_count += 1

        await self.db.commit()

        logger.info(
            "章节映射完成",
            document_id=document_id,
            mapped_count=mapped_count,
            auto_approved=auto_approved,
            pending_review=pending_review,
            rejected=rejected,
        )

        return {
            "document_id": document_id,
            "mapped_count": mapped_count,
            "auto_approved": auto_approved,
            "pending_review": pending_review,
            "rejected": rejected,
        }

    def _build_chapter_index(self, chapters: List[CanonicalChapter]) -> Dict[str, Any]:
        """构建章节匹配索引"""
        index = {}

        for chapter in chapters:
            # 主名称
            name_lower = chapter.name.lower().strip()
            index[name_lower] = {
                'id': chapter.id,
                'level': chapter.level,
                'match_type': 'exact',
            }

            # 别名
            if chapter.aliases:
                for alias in chapter.aliases:
                    alias_lower = alias.lower().strip()
                    if alias_lower not in index:
                        index[alias_lower] = {
                            'id': chapter.id,
                            'level': chapter.level,
                            'match_type': 'alias',
                        }

            # 编码
            if chapter.code:
                code_lower = chapter.code.lower().strip()
                if code_lower not in index:
                    index[code_lower] = {
                        'id': chapter.id,
                        'level': chapter.level,
                        'match_type': 'code',
                    }

        return index

    def _match_section_multi(
        self,
        section: DocumentSection,
        chapter_indices: Dict[str, Dict[str, Any]]
    ) -> Optional[tuple]:
        """
        跨学科匹配 section 到标准章节，取所有学科中置信度最高的匹配

        Returns:
            (chapter_id, confidence, mapping_type) 或 None
        """
        best = None
        for _sid, index in chapter_indices.items():
            result = self._match_section(section, index)
            if result:
                if best is None or result[1] > best[1]:
                    best = result
        return best

    def _match_section(
        self,
        section: DocumentSection,
        chapter_index: Dict[str, Any]
    ) -> Optional[tuple]:
        """
        匹配 section 到标准章节

        Returns:
            (chapter_id, confidence, mapping_type) 或 None
        """
        title = section.title.lower().strip()
        section_path = section.section_path.lower().strip() if section.section_path else ""

        # 1. 精确匹配
        if title in chapter_index:
            info = chapter_index[title]
            return info['id'], 1.0, 'exact'

        # 2. 路径匹配
        if section_path:
            for key, info in chapter_index.items():
                if key in section_path or section_path in key:
                    return info['id'], 0.85, 'partial'

        # 3. 包含匹配
        best_match = None
        best_score = 0.0

        for key, info in chapter_index.items():
            # 检查标题是否包含章节名
            if key in title:
                score = len(key) / max(len(title), 1)
                if score > best_score:
                    best_score = score
                    best_match = (info['id'], 0.7 + score * 0.2, 'partial')

            # 检查章节名是否包含标题
            if title in key and len(title) > 3:  # 避免太短的匹配
                score = len(title) / max(len(key), 1)
                if score > best_score:
                    best_score = score
                    best_match = (info['id'], 0.6 + score * 0.2, 'partial')

        if best_match and best_match[1] >= 0.5:
            return best_match

        # 4. 关键词匹配
        title_words = set(title.replace('>', ' ').replace('  ', ' ').split())
        for key, info in chapter_index.items():
            key_words = set(key.replace('>', ' ').replace('  ', ' ').split())
            common_words = title_words & key_words
            if len(common_words) >= 2:
                score = len(common_words) / max(len(title_words), len(key_words), 1)
                if score > 0.3:
                    return info['id'], 0.5 + score * 0.3, 'related'

        return None

    async def get_section_mappings(
        self,
        document_id: str,
        review_status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取文档的 section 映射列表"""
        query = (
            select(DocumentSectionMapping, DocumentSection, CanonicalChapter)
            .join(DocumentSection, DocumentSectionMapping.document_section_id == DocumentSection.id)
            .join(CanonicalChapter, DocumentSectionMapping.canonical_chapter_id == CanonicalChapter.id)
            .where(DocumentSection.document_id == document_id)
        )

        if review_status:
            query = query.where(DocumentSectionMapping.review_status == review_status)

        query = query.order_by(DocumentSection.page_start)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "mapping_id": mapping.id,
                "section_id": section.id,
                "section_title": section.title,
                "section_path": section.section_path,
                "section_level": section.level,
                "page_start": section.page_start,
                "page_end": section.page_end,
                "canonical_chapter_id": chapter.id,
                "canonical_chapter_name": chapter.name,
                "canonical_chapter_code": chapter.code,
                "mapping_type": mapping.mapping_type,
                "confidence": float(mapping.confidence),
                "review_status": mapping.review_status,
                "review_notes": mapping.review_notes,
            }
            for mapping, section, chapter in rows
        ]

    async def get_chapter_ownership_diagnostics(
        self,
        document_id: str,
        page_no: Optional[int] = None,
        include_blocks: bool = True,
    ) -> Dict[str, Any]:
        """Compatibility delegate for the standalone diagnostics service."""
        return await self.diagnostics.get_chapter_ownership_diagnostics(
            document_id=document_id,
            page_no=page_no,
            include_blocks=include_blocks,
        )

    async def review_mapping(
        self,
        mapping_id: str,
        review_status: str,
        canonical_chapter_id: Optional[str] = None,
        review_notes: Optional[str] = None,
        reviewed_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """审核映射"""
        from datetime import datetime

        result = await self.db.execute(
            select(DocumentSectionMapping).where(DocumentSectionMapping.id == mapping_id)
        )
        mapping = result.scalar_one_or_none()

        if not mapping:
            raise ValueError(f"映射不存在: {mapping_id}")

        # 如果指定了新的标准章节，更新映射
        if canonical_chapter_id:
            mapping.canonical_chapter_id = canonical_chapter_id

        # 同一个 section 只保留一个最终审核结果。
        # 当前映射一旦被审核，其它待审候选需要同步收口，避免审核列表继续冒出同 section 的候选项。
        if review_status == "approved":
            await self.db.execute(
                update(DocumentSectionMapping)
                .where(
                    DocumentSectionMapping.document_section_id == mapping.document_section_id,
                    DocumentSectionMapping.id != mapping.id,
                    DocumentSectionMapping.review_status == "pending",
                )
                .values(
                    review_status="rejected",
                    review_notes="Auto rejected after another candidate on the same section was reviewed.",
                    reviewed_by=reviewed_by,
                    reviewed_at=datetime.utcnow(),
                )
            )

        mapping.review_status = review_status
        mapping.review_notes = review_notes
        mapping.reviewed_by = reviewed_by
        mapping.reviewed_at = datetime.utcnow()

        await self.db.commit()

        logger.info(
            "映射审核完成",
            mapping_id=mapping_id,
            review_status=review_status,
        )

        return {
            "mapping_id": mapping_id,
            "review_status": review_status,
            "canonical_chapter_id": mapping.canonical_chapter_id,
        }

    async def get_pending_review_count(self, subject_id: Optional[str] = None) -> int:
        """获取待审核映射数量"""
        query = select(DocumentSectionMapping).where(
            DocumentSectionMapping.review_status == "pending"
        )

        if subject_id:
            # 需要通过 document 和 canonical_chapter 关联到 subject
            query = (
                select(DocumentSectionMapping)
                .join(DocumentSection, DocumentSectionMapping.document_section_id == DocumentSection.id)
                .join(Document, DocumentSection.document_id == Document.id)
                .join(CanonicalChapter, DocumentSectionMapping.canonical_chapter_id == CanonicalChapter.id)
                .where(
                    and_(
                        DocumentSectionMapping.review_status == "pending",
                        or_(
                            Document.subject_id == subject_id,
                            CanonicalChapter.subject_id == subject_id,
                        )
                    )
                )
            )

        result = await self.db.execute(query)
        return len(result.scalars().all())
