"""
标准章节体系与映射服务

维护 canonical_chapters 表，实现 document_section 到标准章节的映射。
"""

import uuid
from typing import Dict, Any, List, Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    CanonicalChapter, DocumentSection, DocumentSectionMapping,
    Subject
)

logger = get_logger(__name__)


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


class CanonicalChapterService:
    """标准章节服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def init_chapters(self, subject_id: str, chapters: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        初始化学科的标准章节体系

        Args:
            subject_id: 学科ID
            chapters: 章节列表，格式:
                [
                    {
                        "name": "数据结构",
                        "code": "CH1",
                        "aliases": ["DS"],
                        "children": [
                            {"name": "绪论", "code": "CH1.1", "aliases": ["引言"]},
                            ...
                        ]
                    },
                    ...
                ]

        Returns:
            初始化结果
        """
        # 验证学科存在
        subject = await self.db.get(Subject, subject_id)
        if not subject:
            raise ValueError(f"学科不存在: {subject_id}")

        created_count = 0
        chapter_ids = {}

        async def _create_chapter(data: Dict, parent_id: Optional[str], level: int):
            nonlocal created_count

            # 检查是否已存在
            existing = await self.db.execute(
                select(CanonicalChapter).where(
                    and_(
                        CanonicalChapter.subject_id == subject_id,
                        CanonicalChapter.name == data['name'],
                        CanonicalChapter.level == level,
                        or_(
                            CanonicalChapter.parent_id == parent_id,
                            and_(CanonicalChapter.parent_id.is_(None), parent_id.is_(None))
                        )
                    )
                )
            )
            chapter = existing.scalar_one_or_none()

            if not chapter:
                chapter = CanonicalChapter(
                    id=generate_id(),
                    subject_id=subject_id,
                    parent_id=parent_id,
                    level=level,
                    name=data['name'],
                    code=data.get('code'),
                    aliases=data.get('aliases'),
                    description=data.get('description'),
                    sort_order=data.get('sort_order', created_count),
                )
                self.db.add(chapter)
                created_count += 1
                await self.db.flush()

            chapter_ids[data['name']] = chapter.id

            # 递归创建子章节
            for child in data.get('children', []):
                await _create_chapter(child, chapter.id, level + 1)

        for i, chapter_data in enumerate(chapters):
            chapter_data.setdefault('sort_order', i)
            await _create_chapter(chapter_data, None, 1)

        await self.db.commit()

        logger.info(
            "标准章节初始化完成",
            subject_id=subject_id,
            created_count=created_count,
        )

        return {
            "subject_id": subject_id,
            "created_count": created_count,
            "chapter_ids": chapter_ids,
        }

    async def get_chapters(self, subject_id: str) -> List[Dict[str, Any]]:
        """获取学科的标准章节树"""
        result = await self.db.execute(
            select(CanonicalChapter)
            .where(CanonicalChapter.subject_id == subject_id)
            .order_by(CanonicalChapter.sort_order)
        )
        chapters = result.scalars().all()

        if not chapters:
            return []

        # 构建树形结构
        chapter_map = {c.id: self._to_dict(c) for c in chapters}
        root_chapters = []

        for chapter in chapters:
            node = chapter_map[chapter.id]
            if chapter.parent_id and chapter.parent_id in chapter_map:
                parent = chapter_map[chapter.parent_id]
                if 'children' not in parent:
                    parent['children'] = []
                parent['children'].append(node)
            else:
                root_chapters.append(node)

        return root_chapters

    async def get_chapters_flat(self, subject_id: str) -> List[Dict[str, Any]]:
        """获取学科的标准章节平面列表"""
        result = await self.db.execute(
            select(CanonicalChapter)
            .where(CanonicalChapter.subject_id == subject_id)
            .order_by(CanonicalChapter.sort_order)
        )
        chapters = result.scalars().all()
        return [self._to_dict(c) for c in chapters]

    async def search_chapters(
        self,
        subject_id: str,
        keyword: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """搜索标准章节"""
        kw = f"%{keyword}%"
        result = await self.db.execute(
            select(CanonicalChapter)
            .where(
                and_(
                    CanonicalChapter.subject_id == subject_id,
                    or_(
                        CanonicalChapter.name.ilike(kw),
                        CanonicalChapter.code.ilike(kw),
                    )
                )
            )
            .limit(limit)
        )
        chapters = result.scalars().all()
        return [self._to_dict(c) for c in chapters]

    def _to_dict(self, chapter: CanonicalChapter) -> Dict[str, Any]:
        return {
            "id": chapter.id,
            "subject_id": chapter.subject_id,
            "parent_id": chapter.parent_id,
            "level": chapter.level,
            "name": chapter.name,
            "code": chapter.code,
            "aliases": chapter.aliases,
            "description": chapter.description,
            "sort_order": chapter.sort_order,
            "status": chapter.status,
            "created_at": chapter.created_at.isoformat() if chapter.created_at else None,
        }


class ChapterMappingService:
    """章节映射服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def map_sections(
        self,
        document_id: str,
        subject_id: Optional[str] = None,
        auto_approve_threshold: float = 0.90,
        reject_threshold: float = 0.60,
    ) -> Dict[str, Any]:
        """
        将文档的 sections 映射到标准章节

        subject_id 可选：
        - 传入时只匹配该学科的标准章节
        - 不传时遍历所有学科，每个 section 取最佳匹配

        Args:
            document_id: 文档ID
            subject_id: 学科ID（可选）
            auto_approve_threshold: 自动通过阈值
            reject_threshold: 拒绝阈值（低于此值）

        Returns:
            映射结果统计
        """
        # 1. 获取文档的 sections
        sections_result = await self.db.execute(
            select(DocumentSection)
            .where(DocumentSection.document_id == document_id)
            .order_by(DocumentSection.page_start)
        )
        sections = sections_result.scalars().all()

        if not sections:
            return {"mapped_count": 0, "message": "文档没有 sections"}

        # 2. 获取标准章节 — 按学科分组或指定学科
        if subject_id:
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
            # 按学科分组
            chapter_groups: Dict[str, list] = {}
            for ch in all_chapters:
                chapter_groups.setdefault(ch.subject_id, []).append(ch)

        # 3. 删除旧的映射
        section_ids = [s.id for s in sections]
        if section_ids:
            from sqlalchemy import delete
            await self.db.execute(
                delete(DocumentSectionMapping).where(
                    DocumentSectionMapping.document_section_id.in_(section_ids)
                )
            )

        # 4. 构建匹配索引 — 每个学科一个索引
        chapter_indices: Dict[str, Dict[str, Any]] = {}
        for sid, chapters in chapter_groups.items():
            if chapters:
                chapter_indices[sid] = self._build_chapter_index(chapters)

        # 5. 逐个 section 进行映射，跨学科取最佳匹配
        mapped_count = 0
        auto_approved = 0
        pending_review = 0
        rejected = 0

        for section in sections:
            match_result = self._match_section_multi(section, chapter_indices)

            if match_result:
                chapter_id, confidence, mapping_type = match_result

                # 确定审核状态
                if confidence >= auto_approve_threshold:
                    review_status = "approved"
                    auto_approved += 1
                elif confidence >= reject_threshold:
                    review_status = "pending"
                    pending_review += 1
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
