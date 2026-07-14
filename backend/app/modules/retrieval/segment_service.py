"""
检索模块的 Segment 构建服务

从当前可用的知识点、题目和标准章节构建检索单元（RetrievalSegment），
生成 embedding 并写入 Qdrant。

支持：
- 全量构建（按学科/文档）
- 增量构建（指定实体列表）
- 重建（删除旧 segment 后重新生成）
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.qdrant import qdrant_manager
from app.models.mysql_models import (
    CanonicalChapter,
    KnowledgePoint,
    KnowledgePointChapterLink,
    Question,
    QuestionChapterLink,
)
from app.infrastructure.ai.embedding_service import (
    get_embedding_service_from_settings,
)
from app.modules.retrieval.segment_factory import SegmentFactory
from app.modules.retrieval.segment_store import SegmentStore

logger = get_logger(__name__)


class SegmentService:
    """Segment 构建服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding = None  # 惰性加载：首次用时从系统设置读 embedding 配置
        self.qdrant = qdrant_manager
        self.segment_factory = SegmentFactory()
        self.segment_store = SegmentStore(db, self.qdrant)

    async def _ensure_embedding(self):
        """惰性构造 embedding 服务（按系统设置的 embedding 配置）。"""
        if self.embedding is None:
            self.embedding = await get_embedding_service_from_settings(self.db)
        return self.embedding

    # ========== 知识点 segment ==========

    async def build_knowledge_segments(
        self,
        subject_id: Optional[str] = None,
        document_id: Optional[str] = None,
        knowledge_point_ids: Optional[List[str]] = None,
        rebuild: bool = False,
    ) -> Dict[str, Any]:
        """
        为知识点构建 segments

        每个知识点生成 1~2 个 segment：
        - title segment: 标题 + 主题术语（用于精确匹配）
        - content segment: 完整内容（用于语义检索）

        Args:
            subject_id: 学科筛选
            document_id: 文档筛选
            knowledge_point_ids: 指定知识点 ID 列表
            rebuild: 是否先删除旧 segments 再重建

        Returns:
            构建统计
        """
        # 1. 查询知识点
        query = select(KnowledgePoint).where(
            KnowledgePoint.status == "active"
        )
        if subject_id:
            query = query.where(KnowledgePoint.subject_id == subject_id)
        if document_id:
            query = query.where(KnowledgePoint.source_document_id == document_id)
        if knowledge_point_ids:
            query = query.where(KnowledgePoint.id.in_(knowledge_point_ids))

        result = await self.db.execute(query)
        kps = result.scalars().all()

        if not kps:
            return {"segments_count": 0, "message": "没有可用的知识点"}

        # 2. 获取章节关联
        chapter_map = await self._get_chapter_links(
            "knowledge_point",
            [kp.id for kp in kps],
        )

        # 3. 构建草稿并收集待 embedding 文本
        drafts = self.segment_factory.build_knowledge_drafts(kps, chapter_map)
        texts_to_embed = [draft.embedding_text for draft in drafts]

        # 4. 批量生成 embeddings
        logger.info("开始生成 embeddings", count=len(texts_to_embed))
        await self._ensure_embedding()
        embeddings = await self.embedding.embed_batch(texts_to_embed)
        artifacts = self.segment_factory.materialize(
            drafts,
            embeddings,
            entity_label="知识点",
        )
        created = len(artifacts.segments)

        cleanup_warning = await self.segment_store.store_segments(
            entity_type="knowledge_point",
            entity_ids=[kp.id for kp in kps],
            collection=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
            segments=artifacts.segments,
            qdrant_points=artifacts.qdrant_points,
            rebuild=rebuild,
        )

        logger.info("知识点 segments 构建完成", count=created)
        result = {"segments_count": created, "knowledge_points_count": len(kps)}
        if cleanup_warning:
            result["cleanup_warning"] = cleanup_warning
        return result

    # ========== 大纲章节 segment ==========

    async def build_canonical_chapter_segments(
        self,
        subject_id: Optional[str] = None,
        outline_id: Optional[str] = None,
        rebuild: bool = False,
    ) -> Dict[str, Any]:
        """
        为大纲章节（CanonicalChapter）构建 segments

        每个章节生成 1~2 个 segment：
        - title segment: 标题 + keywords（用于精确匹配）
        - content segment: enhanced_description + description（用于语义检索）

        使用增强字段提升与题目/知识点的匹配准确率。

        Args:
            subject_id: 学科筛选
            outline_id: 大纲筛选
            rebuild: 是否先删除旧 segments 再重建

        Returns:
            构建统计
        """
        # 1. 查询大纲章节
        query = select(CanonicalChapter).where(CanonicalChapter.status == "active")
        if subject_id:
            query = query.where(CanonicalChapter.subject_id == subject_id)
        if outline_id:
            query = query.where(CanonicalChapter.outline_id == outline_id)

        result = await self.db.execute(query)
        chapters = result.scalars().all()

        if not chapters:
            return {"segments_count": 0, "message": "没有可用的大纲章节"}

        # 2. 构建草稿并收集待 embedding 文本
        drafts = self.segment_factory.build_chapter_drafts(chapters)
        texts_to_embed = [draft.embedding_text for draft in drafts]

        # 3. 批量生成 embeddings
        logger.info("开始生成大纲章节 embeddings", count=len(texts_to_embed))
        await self._ensure_embedding()
        embeddings = await self.embedding.embed_batch(texts_to_embed)

        artifacts = self.segment_factory.materialize(
            drafts,
            embeddings,
            entity_label="大纲章节",
        )
        created = len(artifacts.segments)

        cleanup_warning = await self.segment_store.store_segments(
            entity_type="canonical_chapter",
            entity_ids=[chapter.id for chapter in chapters],
            collection=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
            segments=artifacts.segments,
            qdrant_points=artifacts.qdrant_points,
            rebuild=rebuild,
        )

        logger.info("大纲章节 segments 构建完成", count=created)
        result = {"segments_count": created, "chapters_count": len(chapters)}
        if cleanup_warning:
            result["cleanup_warning"] = cleanup_warning
        return result

    # ========== 题目 segment ==========

    async def build_question_segments(
        self,
        subject_id: Optional[str] = None,
        document_id: Optional[str] = None,
        question_ids: Optional[List[str]] = None,
        rebuild: bool = False,
    ) -> Dict[str, Any]:
        """
        为题目构建 segments

        每个题目生成 1~3 个 segment：
        - title segment: 题干
        - explanation segment: 解析（如有）
        - option segment: 选项（如有）
        """
        query = select(Question).where(Question.status == "active")
        if subject_id:
            query = query.where(Question.subject_id == subject_id)
        if document_id:
            query = query.where(Question.source_document_id == document_id)
        if question_ids:
            query = query.where(Question.id.in_(question_ids))

        result = await self.db.execute(query)
        questions = result.scalars().all()

        if not questions:
            return {"segments_count": 0, "message": "没有可用的题目"}

        chapter_map = await self._get_chapter_links(
            "question",
            [q.id for q in questions],
        )

        drafts = self.segment_factory.build_question_drafts(
            questions,
            chapter_map,
        )
        texts_to_embed = [draft.embedding_text for draft in drafts]

        # 批量 embedding
        logger.info("开始生成题目 embeddings", count=len(texts_to_embed))
        await self._ensure_embedding()
        embeddings = await self.embedding.embed_batch(texts_to_embed)
        artifacts = self.segment_factory.materialize(
            drafts,
            embeddings,
            entity_label="题目",
        )
        created = len(artifacts.segments)

        cleanup_warning = await self.segment_store.store_segments(
            entity_type="question",
            entity_ids=[q.id for q in questions],
            collection=qdrant_manager.COLLECTION_QUESTION_SEGMENTS,
            segments=artifacts.segments,
            qdrant_points=artifacts.qdrant_points,
            rebuild=rebuild,
        )

        logger.info("题目 segments 构建完成", count=created)
        result = {"segments_count": created, "questions_count": len(questions)}
        if cleanup_warning:
            result["cleanup_warning"] = cleanup_warning
        return result

    # ========== 统一入口 ==========

    async def build_all_segments(
        self,
        subject_id: Optional[str] = None,
        document_id: Optional[str] = None,
        rebuild: bool = False,
    ) -> Dict[str, Any]:
        """构建全部 segments（知识点 + 题目 + 大纲章节）"""
        # 确保 Qdrant collections 存在（维度跟随 embedding 配置）
        await self._ensure_embedding()
        self.qdrant.init_default_collections(vector_size=self.embedding.dimension)

        kp_result = await self.build_knowledge_segments(
            subject_id=subject_id,
            document_id=document_id,
            rebuild=rebuild,
        )
        q_result = await self.build_question_segments(
            subject_id=subject_id,
            document_id=document_id,
            rebuild=rebuild,
        )
        ch_result = await self.build_canonical_chapter_segments(
            subject_id=subject_id,
            rebuild=rebuild,
        )

        return {
            "knowledge_segments": kp_result,
            "question_segments": q_result,
            "chapter_segments": ch_result,
        }

    async def build_document_segments(
        self,
        document_id: str,
        include_knowledge: bool = True,
        include_questions: bool = True,
        rebuild: bool = True,
    ) -> Dict[str, Any]:
        """构建单个文档的实体 segments，不重复重建全量大纲章节。"""
        await self._ensure_embedding()
        self.qdrant.init_default_collections(vector_size=self.embedding.dimension)

        knowledge_result = (
            await self.build_knowledge_segments(
                document_id=document_id,
                rebuild=rebuild,
            )
            if include_knowledge
            else {"segments_count": 0, "skipped": True}
        )
        question_result = (
            await self.build_question_segments(
                document_id=document_id,
                rebuild=rebuild,
            )
            if include_questions
            else {"segments_count": 0, "skipped": True}
        )

        return {
            "knowledge_segments": knowledge_result,
            "question_segments": question_result,
        }

    async def rebuild_entity_segments(
        self,
        entity_type: str,
        entity_id: str,
    ) -> Dict[str, Any]:
        """重建单个知识点或题目的检索单元。"""
        await self._ensure_embedding()
        self.qdrant.init_default_collections(vector_size=self.embedding.dimension)

        if entity_type == "knowledge_point":
            return await self.build_knowledge_segments(
                knowledge_point_ids=[entity_id],
                rebuild=True,
            )
        if entity_type == "question":
            return await self.build_question_segments(
                question_ids=[entity_id],
                rebuild=True,
            )
        raise ValueError(f"不支持的实体类型: {entity_type}")

    async def delete_entity_segments(
        self,
        entity_type: str,
        entity_ids: List[str],
    ) -> None:
        """同步删除实体在 MySQL 与 Qdrant 中的检索单元。"""
        if entity_ids:
            await self.segment_store.delete_segments(entity_type, entity_ids)

    async def commit_entity_segment_removal(
        self,
        entity_type: str,
        entity_ids: List[str],
    ) -> Dict[str, Any]:
        return await self.segment_store.commit_entity_segment_removal(
            entity_type,
            entity_ids,
        )

    # ========== 辅助方法 ==========

    async def _get_chapter_links(
        self, entity_type: str, entity_ids: List[str]
    ) -> Dict[str, List[str]]:
        """获取实体的章节关联映射 {entity_id: [chapter_id, ...]}"""
        if entity_type == "knowledge_point":
            result = await self.db.execute(
                select(KnowledgePointChapterLink).where(
                    KnowledgePointChapterLink.knowledge_point_id.in_(entity_ids)
                )
            )
            links = result.scalars().all()
            chapter_map: Dict[str, List[str]] = {}
            for link in links:
                chapter_map.setdefault(link.knowledge_point_id, []).append(
                    link.canonical_chapter_id
                )
            return chapter_map
        else:
            result = await self.db.execute(
                select(QuestionChapterLink).where(
                    QuestionChapterLink.question_id.in_(entity_ids)
                )
            )
            links = result.scalars().all()
            chapter_map: Dict[str, List[str]] = {}
            for link in links:
                chapter_map.setdefault(link.question_id, []).append(
                    link.canonical_chapter_id
                )
            return chapter_map
