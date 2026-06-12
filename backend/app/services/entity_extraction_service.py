"""
实体抽取服务

从文档的 blocks 中抽取知识点和题目，生成 knowledge_points 和 questions 记录。
"""

import uuid
from typing import Dict, Any, List, Optional

from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    Document, DocumentBlock, DocumentSection, DocumentSectionMapping,
    KnowledgePoint, Question, KnowledgePointChapterLink, QuestionChapterLink,
    EntitySourceLink, CanonicalChapter, RetrievalSegment
)
from app.services.chapter_compat_service import resolve_legacy_chapter_id

logger = get_logger(__name__)


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


class EntityExtractionService:
    """实体抽取服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def extract_entities(
        self,
        document_id: str,
        extract_knowledge: bool = True,
        extract_questions: bool = True,
    ) -> Dict[str, Any]:
        """
        从文档中抽取实体

        学科归属从章节映射反推（canonical_chapter.subject_id），
        不依赖 document.subject_id，因此同一文档的不同 section 可以属于不同学科。

        Args:
            document_id: 文档ID
            extract_knowledge: 是否抽取知识点
            extract_questions: 是否抽取题目

        Returns:
            抽取结果统计
        """
        # 1. 获取文档信息
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            raise ValueError(f"文档不存在: {document_id}")

        # document.subject_id 仅作为 fallback
        fallback_subject_id = document.subject_id

        # 2. 获取 blocks
        blocks_result = await self.db.execute(
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
        )
        blocks = blocks_result.scalars().all()

        if not blocks:
            return {"knowledge_count": 0, "question_count": 0, "message": "文档没有 blocks"}

        # 3. 获取 section 映射，用于确定章节和学科归属
        # page -> {chapter_id, subject_id}
        section_mappings = await self._get_section_mappings(document_id)

        knowledge_count = 0
        question_count = 0

        # 4. 抽取知识点
        if extract_knowledge:
            await self._cleanup_existing_entities(document_id, "knowledge_point")
            knowledge_count = await self._extract_knowledge_points(
                document_id, fallback_subject_id, blocks, section_mappings
            )

        # 5. 抽取题目
        if extract_questions:
            await self._cleanup_existing_entities(document_id, "question")
            question_count = await self._extract_questions(
                document_id, fallback_subject_id, blocks, section_mappings
            )

        await self.db.commit()

        logger.info(
            "实体抽取完成",
            document_id=document_id,
            knowledge_count=knowledge_count,
            question_count=question_count,
        )

        return {
            "document_id": document_id,
            "knowledge_count": knowledge_count,
            "question_count": question_count,
        }

    async def _get_section_mappings(self, document_id: str) -> Dict[int, Dict[str, Optional[str]]]:
        """获取 section 到标准章节的映射关系，同时获取章节对应的学科"""
        result = await self.db.execute(
            select(DocumentSection, DocumentSectionMapping, CanonicalChapter)
            .join(DocumentSectionMapping, DocumentSection.id == DocumentSectionMapping.document_section_id)
            .join(CanonicalChapter, DocumentSectionMapping.canonical_chapter_id == CanonicalChapter.id)
            .where(
                and_(
                    DocumentSection.document_id == document_id,
                    DocumentSectionMapping.review_status.in_(["approved", "pending"])
                )
            )
        )
        rows = result.all()

        # 构建 page -> {chapter_id, subject_id} 的映射
        page_chapter_map: Dict[int, Dict[str, Optional[str]]] = {}
        legacy_chapter_cache: Dict[str, Optional[str]] = {}
        for section, mapping, chapter in rows:
            if section.page_start:
                if chapter.id not in legacy_chapter_cache:
                    legacy_chapter_cache[chapter.id] = await resolve_legacy_chapter_id(
                        self.db,
                        canonical_chapter_id=chapter.id,
                        subject_id=chapter.subject_id,
                    )
                info = {
                    "chapter_id": mapping.canonical_chapter_id,
                    "subject_id": chapter.subject_id,
                    "legacy_chapter_id": legacy_chapter_cache[chapter.id],
                }
                for page in range(section.page_start, (section.page_end or section.page_start) + 1):
                    page_chapter_map[page] = info

        return page_chapter_map

    async def _cleanup_existing_entities(self, document_id: str, entity_type: str) -> None:
        """清理同一文档已抽取的实体，避免重复入库。"""
        model = KnowledgePoint if entity_type == "knowledge_point" else Question
        result = await self.db.execute(
            select(model.id).where(model.source_document_id == document_id)
        )
        entity_ids = [row[0] for row in result.all()]
        if not entity_ids:
            return

        await self.db.execute(
            delete(EntitySourceLink).where(
                and_(
                    EntitySourceLink.entity_type == entity_type,
                    EntitySourceLink.entity_id.in_(entity_ids),
                )
            )
        )
        await self.db.execute(
            delete(RetrievalSegment).where(
                and_(
                    RetrievalSegment.entity_type == entity_type,
                    RetrievalSegment.entity_id.in_(entity_ids),
                )
            )
        )
        await self.db.execute(
            delete(model).where(model.id.in_(entity_ids))
        )

    async def _extract_knowledge_points(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> int:
        """抽取知识点"""
        knowledge_count = 0

        # 简单策略：将连续的 paragraph + title blocks 组合为知识点
        current_title = None
        current_content_blocks = []

        for block in blocks:
            # 如果是标题类型，保存前一个知识点并开始新的
            if block.block_type in ('title', 'heading'):
                # 保存前一个知识点
                if current_title and current_content_blocks:
                    created = await self._save_knowledge_point(
                        document_id, fallback_subject_id, current_title,
                        current_content_blocks, section_mappings
                    )
                    if created:
                        knowledge_count += 1
                    current_content_blocks = []

                current_title = block
            elif block.block_type in ('paragraph', 'list'):
                current_content_blocks.append(block)

        # 保存最后一个知识点
        if current_title and current_content_blocks:
            created = await self._save_knowledge_point(
                document_id, fallback_subject_id, current_title,
                current_content_blocks, section_mappings
            )
            if created:
                knowledge_count += 1

        return knowledge_count

    async def _save_knowledge_point(
        self,
        document_id: str,
        fallback_subject_id: str,
        title_block: DocumentBlock,
        content_blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> bool:
        """保存单个知识点"""
        # 从章节映射推断学科和章节（同一文档不同块可属于不同学科）
        mapping_info = section_mappings.get(title_block.page_no)
        primary_chapter_id = mapping_info["chapter_id"] if mapping_info else None
        subject_id = mapping_info["subject_id"] if mapping_info else fallback_subject_id
        legacy_chapter_id = mapping_info["legacy_chapter_id"] if mapping_info else None
        if not legacy_chapter_id:
            legacy_chapter_id = await resolve_legacy_chapter_id(self.db, subject_id=subject_id)

        # 组合内容
        content_parts = []
        for block in content_blocks:
            text = block.content_md or block.content_text or ""
            if text.strip():
                content_parts.append(text.strip())
        content = "\n\n".join(content_parts)

        if not content:
            return False
        if not subject_id or not legacy_chapter_id:
            logger.warning(
                "知识点缺少有效章节归属，跳过入库",
                document_id=document_id,
                block_id=title_block.id,
            )
            return False

        # 生成 topic_terms（简单实现：从标题和内容中提取关键词）
        topic_terms = self._extract_topic_terms(title_block.content_text or "", content)

        # 创建知识点
        kp_id = generate_id()
        knowledge_point = KnowledgePoint(
            id=kp_id,
            chapter_id=legacy_chapter_id,
            subject_id=subject_id,
            primary_chapter_id=primary_chapter_id,
            source_document_id=document_id,
            title=title_block.content_text or "未命名知识点",
            canonical_title=title_block.content_text,
            content=content,
            topic_terms=topic_terms,
            review_status="pending",
        )
        self.db.add(knowledge_point)

        # 创建章节关联
        if primary_chapter_id:
            link = KnowledgePointChapterLink(
                knowledge_point_id=kp_id,
                canonical_chapter_id=primary_chapter_id,
                is_primary=True,
            )
            self.db.add(link)

        # 创建来源引用
        source_link = EntitySourceLink(
            entity_type="knowledge_point",
            entity_id=kp_id,
            document_id=document_id,
            page_start=title_block.page_no,
            page_end=content_blocks[-1].page_no if content_blocks else title_block.page_no,
            block_ids=[title_block.id] + [b.id for b in content_blocks],
            excerpt_text=content[:500] if content else None,
        )
        self.db.add(source_link)

        await self.db.flush()
        return True

    async def _extract_questions(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> int:
        """抽取题目"""
        question_count = 0

        # 简单策略：查找包含题目标记的 blocks
        # 题目通常以 "第X题"、"X."、"（X）" 等开头
        question_markers = ['第', '题', '（', '(', 'A.', 'B.', 'C.', 'D.']

        current_question_blocks = []
        in_question = False

        for block in blocks:
            text = (block.content_text or "").strip()

            # 检测题目开始
            is_question_start = False
            if block.block_type in ('paragraph', 'heading'):
                # 检查是否是题号
                for marker in question_markers:
                    if text.startswith(marker):
                        is_question_start = True
                        break

            if is_question_start:
                # 保存前一个题目
                if in_question and current_question_blocks:
                    created = await self._save_question(
                        document_id, fallback_subject_id, current_question_blocks, section_mappings
                    )
                    if created:
                        question_count += 1
                    current_question_blocks = []

                in_question = True
                current_question_blocks.append(block)
            elif in_question:
                # 如果遇到新的标题，结束当前题目
                if block.block_type in ('title', 'heading'):
                    if current_question_blocks:
                        created = await self._save_question(
                            document_id, fallback_subject_id, current_question_blocks, section_mappings
                        )
                        if created:
                            question_count += 1
                        current_question_blocks = []
                    in_question = False
                else:
                    current_question_blocks.append(block)

        # 保存最后一个题目
        if in_question and current_question_blocks:
            created = await self._save_question(
                document_id, fallback_subject_id, current_question_blocks, section_mappings
            )
            if created:
                question_count += 1

        return question_count

    async def _save_question(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> bool:
        """保存单个题目"""
        if not blocks:
            return False

        first_block = blocks[0]
        mapping_info = section_mappings.get(first_block.page_no)
        primary_chapter_id = mapping_info["chapter_id"] if mapping_info else None
        subject_id = mapping_info["subject_id"] if mapping_info else fallback_subject_id
        legacy_chapter_id = mapping_info["legacy_chapter_id"] if mapping_info else None
        if not legacy_chapter_id:
            legacy_chapter_id = await resolve_legacy_chapter_id(self.db, subject_id=subject_id)

        # 组合题目内容
        content_parts = []
        for block in blocks:
            text = block.content_md or block.content_text or ""
            if text.strip():
                content_parts.append(text.strip())
        content = "\n".join(content_parts)

        if not content:
            return False
        if not subject_id or not legacy_chapter_id:
            logger.warning(
                "题目缺少有效章节归属，跳过入库",
                document_id=document_id,
                block_id=first_block.id,
            )
            return False

        # 简单判断题型
        question_type = "short_answer"  # 默认简答
        if any(kw in content for kw in ['A.', 'B.', 'C.', 'D.', 'A、', 'B、', 'C、', 'D、']):
            question_type = "choice"
        elif '判断' in content[:50]:
            question_type = "judge"
        elif '填空' in content[:50]:
            question_type = "fill"

        # 创建题目
        q_id = generate_id()
        question = Question(
            id=q_id,
            subject_id=subject_id,
            chapter_id=legacy_chapter_id,
            primary_chapter_id=primary_chapter_id,
            source_document_id=document_id,
            type=question_type,
            content=content,
            answer="",  # 需要后续从 blocks 中提取或人工补充
            review_status="pending",
        )
        self.db.add(question)

        # 创建章节关联
        if primary_chapter_id:
            link = QuestionChapterLink(
                question_id=q_id,
                canonical_chapter_id=primary_chapter_id,
                is_primary=True,
            )
            self.db.add(link)

        # 创建来源引用
        source_link = EntitySourceLink(
            entity_type="question",
            entity_id=q_id,
            document_id=document_id,
            page_start=first_block.page_no,
            page_end=blocks[-1].page_no,
            block_ids=[b.id for b in blocks],
            excerpt_text=content[:500],
        )
        self.db.add(source_link)

        await self.db.flush()
        return True

    def _extract_topic_terms(self, title: str, content: str) -> List[str]:
        """提取主题术语（简单实现）"""
        terms = set()

        # 从标题提取
        if title:
            # 去除常见前缀
            clean_title = title.strip()
            for prefix in ['第', '章', '节', '、', '。', '：', ':', ' ']:
                clean_title = clean_title.replace(prefix, ' ')
            words = clean_title.split()
            for word in words:
                if len(word) >= 2:
                    terms.add(word)

        # 从内容提取高频词（简单实现）
        # 实际应该使用 NLP 工具提取关键词
        if content:
            # 提取引号中的术语
            import re
            quoted = re.findall(r'[「「""]([^」」""]+)[」」""]', content)
            for q in quoted:
                if 2 <= len(q) <= 20:
                    terms.add(q)

        return list(terms)[:20]  # 限制数量

    async def get_entity_source_links(
        self,
        entity_type: str,
        entity_id: str
    ) -> List[Dict[str, Any]]:
        """获取实体的来源引用"""
        result = await self.db.execute(
            select(EntitySourceLink)
            .where(
                and_(
                    EntitySourceLink.entity_type == entity_type,
                    EntitySourceLink.entity_id == entity_id,
                )
            )
        )
        links = result.scalars().all()

        return [
            {
                "id": link.id,
                "entity_type": link.entity_type,
                "entity_id": link.entity_id,
                "document_id": link.document_id,
                "page_start": link.page_start,
                "page_end": link.page_end,
                "block_ids": link.block_ids,
                "excerpt_text": link.excerpt_text,
                "created_at": link.created_at.isoformat() if link.created_at else None,
            }
            for link in links
        ]
