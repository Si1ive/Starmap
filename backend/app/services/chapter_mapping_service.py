"""
标准章节体系与映射服务

维护 canonical_chapters 表，实现 document_section 到标准章节的映射。
"""

import re
import uuid
from collections import Counter, defaultdict
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy import select, and_, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    CanonicalChapter, DocumentSection, DocumentSectionMapping,
    Document, DocumentBlock, DocumentPage, EntitySourceLink,
    Subject
)

logger = get_logger(__name__)

DIAG_OPTION_BLOCK_RE = re.compile(r'^\s*[A-H]\s*[.．、:：]\s*\S+')
DIAG_QUESTION_NUMERIC_RE = re.compile(r'^\s*\d{1,3}(?:\s*[.、．。]\s*|\s+)(?=\S)')
DIAG_QUESTION_PAREN_RE = re.compile(r'^\s*[（(]\s*\d{1,3}\s*[）)]\s*\S+')
DIAG_QUESTION_TITLE_RE = re.compile(r'^\s*第\s*[一二三四五六七八九十百千\d]+\s*题')
DIAG_QUESTION_CUE_RE = re.compile(
    r'[?？]|下列|以下|关于|若|设|已知|正确|错误|不是|可以|能够|应|属于|采用|'
    r'给出|求|计算|证明|说明|分析|为什么|多少|哪个|哪些|如果|判断'
)

# 试卷类文档不走标题树/章节映射这一层
EXAM_DOC_TYPES = {"past_exam", "mock_exam"}


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


def _float_or_none(value: Any) -> Optional[float]:
    return float(value) if value is not None else None


def _block_text(block: DocumentBlock) -> str:
    return (block.content_text or block.content_md or "").strip()


def _text_excerpt(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _looks_like_option_block(text: str) -> bool:
    return bool(DIAG_OPTION_BLOCK_RE.match(text or ""))


def _looks_like_question_start(text: str, block_type: str) -> bool:
    if not text or block_type not in ("paragraph", "heading", "list"):
        return False
    if _looks_like_option_block(text):
        return False
    if DIAG_QUESTION_TITLE_RE.match(text):
        return True
    if DIAG_QUESTION_PAREN_RE.match(text):
        return bool(DIAG_QUESTION_CUE_RE.search(text)) or len(text) > 20
    if DIAG_QUESTION_NUMERIC_RE.match(text):
        return bool(DIAG_QUESTION_CUE_RE.search(text)) or len(text) > 20
    return False


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
        force: bool = False,
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

        mappings_by_section: Dict[str, List[Tuple[DocumentSectionMapping, CanonicalChapter, Subject]]] = defaultdict(list)
        for mapping, section, chapter, subject in mapping_rows:
            mappings_by_section[section.id].append((mapping, chapter, subject))

        accepted_page_mappings: Dict[int, Dict[str, Any]] = {}
        for section in sections:
            accepted_mapping = self._select_mapping_for_section(section.id, mappings_by_section, accepted_only=True)
            if not accepted_mapping or not section.page_start:
                continue
            page_start = section.page_start
            page_end = section.page_end or section.page_start
            for current_page in range(page_start, page_end + 1):
                accepted_page_mappings[current_page] = self._mapping_to_dict(
                    *accepted_mapping,
                    section=section,
                    source="section_range",
                    fallback_distance=0,
                )

        page_numbers = await self._get_document_page_numbers(document_id, all_blocks, document.page_count)
        if page_no is not None:
            page_numbers = [page for page in page_numbers if page == page_no]

        entity_index = await self._build_entity_source_index(document_id)

        section_ranges = [
            self._section_range(section, block_index, len(all_blocks))
            for section in sections
        ]

        page_items = []
        for current_page in page_numbers:
            page_blocks = [block for block in all_blocks if block.page_no == current_page]
            active_section = self._section_for_page(current_page, section_ranges)
            raw_section_mapping = (
                self._select_mapping_for_section(active_section["section"].id, mappings_by_section)
                if active_section
                else None
            )
            section_mapping = None
            if active_section and raw_section_mapping:
                section_mapping = self._mapping_to_dict(
                    *raw_section_mapping,
                    section=active_section["section"],
                    source="native_section",
                    fallback_distance=0,
                )
            extraction_mapping = self._resolve_page_mapping(current_page, accepted_page_mappings)
            page_entities = entity_index["pages"].get(current_page, {})
            page_issues = self._page_issues(active_section, section_mapping, extraction_mapping, is_exam_doc)

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
                "native_section": self._section_to_diag_dict(active_section["section"]) if active_section else None,
                "section_mapping": section_mapping,
                "extraction_mapping": extraction_mapping,
                "diagnostic_status": self._diagnostic_status(page_issues),
                "issues": page_issues,
                "extracted": {
                    "knowledge_count": page_entities.get("knowledge_point", 0),
                    "question_count": page_entities.get("question", 0),
                },
            })

        block_items = []
        if include_blocks:
            for block in blocks:
                text = _block_text(block)
                active_section = self._section_for_block(block, block_index, section_ranges)
                selected_mapping = None
                if active_section:
                    raw_selected = self._select_mapping_for_section(
                        active_section["section"].id,
                        mappings_by_section,
                    )
                    if raw_selected:
                        selected_mapping = self._mapping_to_dict(
                            *raw_selected,
                            section=active_section["section"],
                            source="native_section",
                            fallback_distance=0,
                        )

                extraction_mapping = self._resolve_page_mapping(block.page_no, accepted_page_mappings)
                block_entities = entity_index["blocks"].get(block.id, {})
                block_issues = self._block_issues(active_section, selected_mapping, extraction_mapping, is_exam_doc)

                block_items.append({
                    "id": block.id,
                    "page_no": block.page_no,
                    "order_no": block.order_no,
                    "block_type": block.block_type,
                    "text_excerpt": _text_excerpt(text),
                    "text_length": len(text),
                    "signals": {
                        "looks_like_question_start": _looks_like_question_start(text, block.block_type),
                        "looks_like_option": _looks_like_option_block(text),
                        "looks_like_heading": block.block_type in ("title", "heading"),
                    },
                    "native_section": self._section_to_diag_dict(active_section["section"]) if active_section else None,
                    "section_mapping": selected_mapping,
                    "extraction_mapping": extraction_mapping,
                    "diagnostic_status": self._diagnostic_status(block_issues),
                    "issues": block_issues,
                    "extracted": {
                        "knowledge_count": block_entities.get("knowledge_point", 0),
                        "question_count": block_entities.get("question", 0),
                    },
                })

        status_counter = Counter(page["diagnostic_status"] for page in page_items)
        block_status_counter = Counter(block["diagnostic_status"] for block in block_items)
        pages_with_questions = [page for page in page_items if page["question_start_count"] > 0]
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
                "unmapped_sections": sum(1 for section in sections if not mappings_by_section.get(section.id)),
                "pages_ok": status_counter.get("ok", 0),
                "pages_warning": status_counter.get("warning", 0),
                "pages_error": status_counter.get("error", 0),
                "blocks_ok": block_status_counter.get("ok", 0),
                "blocks_warning": block_status_counter.get("warning", 0),
                "blocks_error": block_status_counter.get("error", 0),
                "question_like_blocks": sum(page["question_start_count"] for page in page_items),
                "question_pages_without_stable_mapping": len(pages_with_question_without_mapping),
                "extracted_knowledge_count": entity_index["entity_totals"].get("knowledge_point", 0),
                "extracted_question_count": entity_index["entity_totals"].get("question", 0),
            },
            "pages": page_items,
            "blocks": block_items,
            "sections": [
                self._section_with_mapping_to_diag_dict(section, mappings_by_section)
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

    def _section_range(
        self,
        section: DocumentSection,
        block_index: Dict[str, int],
        total_blocks: int,
    ) -> Dict[str, Any]:
        start_idx = block_index.get(section.block_start_id) if section.block_start_id else None
        end_idx = block_index.get(section.block_end_id) if section.block_end_id else None
        if start_idx is None:
            start_idx = 0
        if end_idx is None:
            end_idx = max(total_blocks - 1, start_idx)
        if end_idx < start_idx:
            end_idx = start_idx
        return {
            "section": section,
            "start_idx": start_idx,
            "end_idx": end_idx,
        }

    def _section_for_page(
        self,
        page_no: int,
        section_ranges: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        candidates = []
        for section_range in section_ranges:
            section = section_range["section"]
            if not section.page_start:
                continue
            page_end = section.page_end or section.page_start
            if section.page_start <= page_no <= page_end:
                candidates.append(section_range)
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item["section"].level,
                item["section"].page_start or 0,
                item["start_idx"],
            ),
        )

    def _section_for_block(
        self,
        block: DocumentBlock,
        block_index: Dict[str, int],
        section_ranges: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        block_idx = block_index.get(block.id)
        candidates = []
        for section_range in section_ranges:
            section = section_range["section"]
            page_end = section.page_end or section.page_start
            page_matches = (
                section.page_start is not None
                and page_end is not None
                and section.page_start <= block.page_no <= page_end
            )
            index_matches = (
                block_idx is not None
                and section_range["start_idx"] <= block_idx <= section_range["end_idx"]
            )
            if page_matches and index_matches:
                candidates.append(section_range)
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item["section"].level,
                item["section"].page_start or 0,
                item["start_idx"],
            ),
        )

    def _select_mapping_for_section(
        self,
        section_id: str,
        mappings_by_section: Dict[str, List[Tuple[DocumentSectionMapping, CanonicalChapter, Subject]]],
        accepted_only: bool = False,
    ) -> Optional[Tuple[DocumentSectionMapping, CanonicalChapter, Subject]]:
        mappings = mappings_by_section.get(section_id, [])
        if accepted_only:
            mappings = [item for item in mappings if item[0].review_status in ("approved", "pending")]
        if not mappings:
            return None
        return max(
            mappings,
            key=lambda item: (
                1 if item[0].review_status in ("approved", "pending") else 0,
                _float_or_none(item[0].confidence) or 0,
            ),
        )

    def _resolve_page_mapping(
        self,
        page_no: Optional[int],
        page_mappings: Dict[int, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if page_no is None or not page_mappings:
            return None
        if page_no in page_mappings:
            return {**page_mappings[page_no], "source": "section_range", "fallback_distance": 0}

        previous_pages = [page for page in page_mappings if page <= page_no]
        if previous_pages:
            previous_page = max(previous_pages)
            return {
                **page_mappings[previous_page],
                "source": "previous_page",
                "fallback_distance": page_no - previous_page,
            }

        next_pages = [page for page in page_mappings if page > page_no]
        if next_pages:
            next_page = min(next_pages)
            return {
                **page_mappings[next_page],
                "source": "next_page",
                "fallback_distance": next_page - page_no,
            }
        return None

    def _section_to_diag_dict(self, section: DocumentSection) -> Dict[str, Any]:
        return {
            "id": section.id,
            "title": section.title,
            "section_path": section.section_path,
            "level": section.level,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "block_start_id": section.block_start_id,
            "block_end_id": section.block_end_id,
            "confidence": _float_or_none(section.confidence),
        }

    def _section_with_mapping_to_diag_dict(
        self,
        section: DocumentSection,
        mappings_by_section: Dict[str, List[Tuple[DocumentSectionMapping, CanonicalChapter, Subject]]],
    ) -> Dict[str, Any]:
        raw_mapping = self._select_mapping_for_section(section.id, mappings_by_section)
        return {
            **self._section_to_diag_dict(section),
            "mapping": (
                self._mapping_to_dict(
                    *raw_mapping,
                    section=section,
                    source="native_section",
                    fallback_distance=0,
                )
                if raw_mapping
                else None
            ),
        }

    def _mapping_to_dict(
        self,
        mapping: DocumentSectionMapping,
        chapter: CanonicalChapter,
        subject: Subject,
        section: DocumentSection,
        source: str,
        fallback_distance: int,
    ) -> Dict[str, Any]:
        return {
            "mapping_id": mapping.id,
            "section_id": section.id,
            "section_title": section.title,
            "section_path": section.section_path,
            "canonical_chapter_id": chapter.id,
            "canonical_chapter_name": chapter.name,
            "canonical_chapter_code": chapter.code,
            "subject_id": subject.id,
            "subject_name": subject.name,
            "mapping_type": mapping.mapping_type,
            "confidence": _float_or_none(mapping.confidence),
            "review_status": mapping.review_status,
            "source": source,
            "fallback_distance": fallback_distance,
        }

    def _page_issues(
        self,
        active_section: Optional[Dict[str, Any]],
        section_mapping: Optional[Dict[str, Any]],
        extraction_mapping: Optional[Dict[str, Any]],
        is_exam_doc: bool = False,
    ) -> List[Dict[str, str]]:
        if is_exam_doc:
            # 试卷类不应有原生章节，只关心是否有可用归属（学科+章节）
            if not extraction_mapping:
                return [{
                    "code": "exam_no_chapter_mapping",
                    "severity": "error",
                    "message": "试卷类文档需要在抽取时显式指定学科或题目级章节归属",
                }]
            return []
        if not active_section:
            return [{
                "code": "no_native_section",
                "severity": "warning",
                "message": "该页没有原生标题树覆盖，抽取只能依赖相邻页章节归属或兜底学科",
            }]
        return self._ownership_issues(section_mapping, extraction_mapping)

    def _block_issues(
        self,
        active_section: Optional[Dict[str, Any]],
        section_mapping: Optional[Dict[str, Any]],
        extraction_mapping: Optional[Dict[str, Any]],
        is_exam_doc: bool = False,
    ) -> List[Dict[str, str]]:
        if is_exam_doc:
            if not extraction_mapping:
                return [{
                    "code": "exam_no_chapter_mapping",
                    "severity": "warning",
                    "message": "试卷类文档需要在抽取时显式指定学科",
                }]
            return []
        if not active_section:
            return [{
                "code": "no_native_section",
                "severity": "warning",
                "message": "该块没有原生标题树覆盖",
            }]
        return self._ownership_issues(section_mapping, extraction_mapping)

    def _ownership_issues(
        self,
        section_mapping: Optional[Dict[str, Any]],
        extraction_mapping: Optional[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        issues = []
        if not section_mapping:
            if extraction_mapping:
                issues.append({
                    "code": "section_unmapped_using_fallback",
                    "severity": "warning",
                    "message": "当前原生章节未映射，抽取将使用相邻页或范围内已有映射",
                })
            else:
                issues.append({
                    "code": "section_unmapped",
                    "severity": "error",
                    "message": "当前原生章节没有可用标准章节映射",
                })
            return issues

        if section_mapping.get("review_status") == "rejected":
            if extraction_mapping:
                issues.append({
                    "code": "section_mapping_rejected_using_fallback",
                    "severity": "warning",
                    "message": "当前章节映射已拒绝，抽取会跳过它并使用其他可用映射",
                })
            else:
                issues.append({
                    "code": "section_mapping_rejected",
                    "severity": "error",
                    "message": "当前章节映射已拒绝，抽取没有可用章节归属",
                })
            return issues

        if not extraction_mapping:
            issues.append({
                "code": "no_extraction_mapping",
                "severity": "error",
                "message": "章节映射存在，但抽取链路没有解析到可用页级归属",
            })
            return issues

        if extraction_mapping.get("source") in ("previous_page", "next_page"):
            issues.append({
                "code": "extraction_mapping_from_neighbor_page",
                "severity": "warning",
                "message": "抽取归属来自相邻页回退，建议检查标题树页码范围",
            })

        if section_mapping.get("canonical_chapter_id") != extraction_mapping.get("canonical_chapter_id"):
            issues.append({
                "code": "native_section_mapping_differs_from_extraction",
                "severity": "warning",
                "message": "原生章节自身映射与抽取最终归属不一致",
            })

        return issues

    def _diagnostic_status(self, issues: List[Dict[str, str]]) -> str:
        if any(issue.get("severity") == "error" for issue in issues):
            return "error"
        if issues:
            return "warning"
        return "ok"

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
