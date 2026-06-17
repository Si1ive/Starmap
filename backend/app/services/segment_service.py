"""
Segment 构建服务

从已审核的知识点和题目构建检索单元（RetrievalSegment），
生成 embedding 并写入 Qdrant。

支持：
- 全量构建（按学科/文档）
- 增量构建（指定实体列表）
- 重建（删除旧 segment 后重新生成）
"""

import uuid
from typing import Dict, Any, List, Optional

from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue

from app.core.logging import get_logger
from app.db.qdrant import QdrantManager, qdrant_manager
from app.models.mysql_models import (
    KnowledgePoint, Question, RetrievalSegment,
    KnowledgePointChapterLink, QuestionChapterLink,
    EntitySourceLink, Document
)
from app.services.embedding_service import get_embedding_service

logger = get_logger(__name__)


def _gen_id() -> str:
    return uuid.uuid4().hex[:32]


def _gen_qdrant_id() -> str:
    return str(uuid.uuid4())


class SegmentService:
    """Segment 构建服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding = get_embedding_service()
        self.qdrant = qdrant_manager

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
            KnowledgePoint.review_status == "approved"
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
            return {"segments_count": 0, "message": "没有已审核的知识点"}

        # 2. 如需重建，先删除旧 segments
        if rebuild:
            kp_ids = [kp.id for kp in kps]
            await self._delete_segments("knowledge_point", kp_ids)

        # 3. 获取章节关联
        chapter_map = await self._get_chapter_links("knowledge_point", [kp.id for kp in kps])

        # 4. 构建 segments 并收集待 embedding 文本
        segments_to_create: List[Dict[str, Any]] = []
        texts_to_embed: List[str] = []

        for kp in kps:
            chapter_ids = chapter_map.get(kp.id, [])

            # title segment
            title_text = kp.title
            if kp.topic_terms:
                title_text += " " + " ".join(kp.topic_terms)

            segments_to_create.append({
                "entity_type": "knowledge_point",
                "entity_id": kp.id,
                "document_id": kp.source_document_id,
                "segment_type": "title",
                "content_text": title_text,
                "content_md": f"# {kp.title}",
                "sparse_text": title_text,
                "subject_id": kp.subject_id,
                "chapter_ids": chapter_ids,
                "topic_terms": kp.topic_terms,
            })
            texts_to_embed.append(title_text)

            # content segment（内容不为空时生成）
            if kp.content:
                context_text = f"{kp.title}\n\n{kp.content}"
                segments_to_create.append({
                    "entity_type": "knowledge_point",
                    "entity_id": kp.id,
                    "document_id": kp.source_document_id,
                    "segment_type": "content",
                    "content_text": kp.content,
                    "content_md": kp.content,
                    "sparse_text": self._build_sparse_text(kp.title, kp.content, kp.topic_terms),
                    "context_text": context_text,
                    "subject_id": kp.subject_id,
                    "chapter_ids": chapter_ids,
                    "topic_terms": kp.topic_terms,
                })
                texts_to_embed.append(context_text)

        # 5. 批量生成 embeddings
        logger.info("开始生成 embeddings", count=len(texts_to_embed))
        embeddings = await self.embedding.embed_batch(texts_to_embed)

        # 6. 写入 MySQL + Qdrant
        created = 0
        qdrant_points: List[PointStruct] = []

        for seg_data, vector in zip(segments_to_create, embeddings):
            seg_id = _gen_id()
            qdrant_point_id = _gen_qdrant_id()

            # MySQL
            segment = RetrievalSegment(
                id=seg_id,
                entity_type=seg_data["entity_type"],
                entity_id=seg_data["entity_id"],
                document_id=seg_data.get("document_id"),
                segment_type=seg_data["segment_type"],
                content_text=seg_data["content_text"],
                content_md=seg_data.get("content_md"),
                sparse_text=seg_data.get("sparse_text"),
                context_text=seg_data.get("context_text"),
                subject_id=seg_data.get("subject_id"),
                chapter_ids=seg_data.get("chapter_ids"),
                topic_terms=seg_data.get("topic_terms"),
                qdrant_point_id=qdrant_point_id,
            )
            self.db.add(segment)

            # Qdrant payload
            collection = qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS
            payload = {
                "segment_id": seg_id,
                "entity_id": seg_data["entity_id"],
                "segment_type": seg_data["segment_type"],
                "subject_id": seg_data.get("subject_id"),
                "chapter_ids": seg_data.get("chapter_ids", []),
                "topic_terms": seg_data.get("topic_terms", []),
                "content_preview": seg_data["content_text"][:200],
            }

            qdrant_points.append(
                PointStruct(id=qdrant_point_id, vector=vector, payload=payload)
            )
            created += 1

        # 批量写入 Qdrant
        if qdrant_points:
            self.qdrant.upsert_points(
                qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS, qdrant_points
            )

        await self.db.commit()

        logger.info("知识点 segments 构建完成", count=created)
        return {"segments_count": created, "knowledge_points_count": len(kps)}

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
        query = select(Question).where(Question.review_status == "approved")
        if subject_id:
            query = query.where(Question.subject_id == subject_id)
        if document_id:
            query = query.where(Question.source_document_id == document_id)
        if question_ids:
            query = query.where(Question.id.in_(question_ids))

        result = await self.db.execute(query)
        questions = result.scalars().all()

        if not questions:
            return {"segments_count": 0, "message": "没有已审核的题目"}

        if rebuild:
            q_ids = [q.id for q in questions]
            await self._delete_segments("question", q_ids)

        chapter_map = await self._get_chapter_links("question", [q.id for q in questions])

        segments_to_create: List[Dict[str, Any]] = []
        texts_to_embed: List[str] = []

        for q in questions:
            chapter_ids = chapter_map.get(q.id, [])

            # title segment（题干）
            title_text = q.content or ""
            if q.question_no:
                title_text = f"[{q.question_no}] {title_text}"

            segments_to_create.append({
                "entity_type": "question",
                "entity_id": q.id,
                "document_id": q.source_document_id,
                "segment_type": "title",
                "content_text": title_text,
                "sparse_text": title_text,
                "subject_id": q.subject_id,
                "chapter_ids": chapter_ids,
                "topic_terms": q.topic_terms,
            })
            texts_to_embed.append(title_text)

            # explanation segment
            if q.explanation:
                context_text = f"{title_text}\n\n解析：{q.explanation}"
                segments_to_create.append({
                    "entity_type": "question",
                    "entity_id": q.id,
                    "document_id": q.source_document_id,
                    "segment_type": "explanation",
                    "content_text": q.explanation,
                    "context_text": context_text,
                    "sparse_text": self._build_sparse_text(title_text, q.explanation, q.topic_terms),
                    "subject_id": q.subject_id,
                    "chapter_ids": chapter_ids,
                    "topic_terms": q.topic_terms,
                })
                texts_to_embed.append(context_text)

            # option segment（选择题）
            if q.options and q.type in ("choice", "single_choice", "multi_choice", "multiple_choice"):
                option_text = "\n".join(
                    f"{opt.get('key') or opt.get('label') or opt.get('option_label') or ''}. {opt.get('text', '')}"
                    for opt in q.options
                    if isinstance(opt, dict)
                )
                if option_text:
                    segments_to_create.append({
                        "entity_type": "question",
                        "entity_id": q.id,
                        "document_id": q.source_document_id,
                        "segment_type": "option",
                        "content_text": option_text,
                        "sparse_text": option_text,
                        "subject_id": q.subject_id,
                        "chapter_ids": chapter_ids,
                        "topic_terms": q.topic_terms,
                    })
                    texts_to_embed.append(option_text)

        # 批量 embedding
        logger.info("开始生成题目 embeddings", count=len(texts_to_embed))
        embeddings = await self.embedding.embed_batch(texts_to_embed)

        # 写入
        created = 0
        qdrant_points: List[PointStruct] = []

        for seg_data, vector in zip(segments_to_create, embeddings):
            seg_id = _gen_id()
            qdrant_point_id = _gen_qdrant_id()

            segment = RetrievalSegment(
                id=seg_id,
                entity_type=seg_data["entity_type"],
                entity_id=seg_data["entity_id"],
                document_id=seg_data.get("document_id"),
                segment_type=seg_data["segment_type"],
                content_text=seg_data["content_text"],
                content_md=seg_data.get("content_md"),
                sparse_text=seg_data.get("sparse_text"),
                context_text=seg_data.get("context_text"),
                subject_id=seg_data.get("subject_id"),
                chapter_ids=seg_data.get("chapter_ids"),
                topic_terms=seg_data.get("topic_terms"),
                qdrant_point_id=qdrant_point_id,
            )
            self.db.add(segment)

            collection = qdrant_manager.COLLECTION_QUESTION_SEGMENTS
            payload = {
                "segment_id": seg_id,
                "entity_id": seg_data["entity_id"],
                "segment_type": seg_data["segment_type"],
                "subject_id": seg_data.get("subject_id"),
                "chapter_ids": seg_data.get("chapter_ids", []),
                "topic_terms": seg_data.get("topic_terms", []),
                "content_preview": seg_data["content_text"][:200],
            }

            qdrant_points.append(
                PointStruct(id=qdrant_point_id, vector=vector, payload=payload)
            )
            created += 1

        if qdrant_points:
            self.qdrant.upsert_points(
                qdrant_manager.COLLECTION_QUESTION_SEGMENTS, qdrant_points
            )

        await self.db.commit()

        logger.info("题目 segments 构建完成", count=created)
        return {"segments_count": created, "questions_count": len(questions)}

    # ========== 统一入口 ==========

    async def build_all_segments(
        self,
        subject_id: Optional[str] = None,
        document_id: Optional[str] = None,
        rebuild: bool = False,
    ) -> Dict[str, Any]:
        """构建全部 segments（知识点 + 题目）"""
        # 确保 Qdrant collections 存在
        self.qdrant.init_default_collections()

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

        return {
            "knowledge_segments": kp_result,
            "question_segments": q_result,
        }

    # ========== 辅助方法 ==========

    async def _delete_segments(self, entity_type: str, entity_ids: List[str]):
        """删除指定实体的旧 segments（MySQL + Qdrant）"""
        result = await self.db.execute(
            select(RetrievalSegment).where(
                and_(
                    RetrievalSegment.entity_type == entity_type,
                    RetrievalSegment.entity_id.in_(entity_ids),
                )
            )
        )
        old_segments = result.scalars().all()

        # 收集 Qdrant point IDs 按 collection 分组
        collection = (
            qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS
            if entity_type == "knowledge_point"
            else qdrant_manager.COLLECTION_QUESTION_SEGMENTS
        )
        qdrant_ids = [s.qdrant_point_id for s in old_segments if s.qdrant_point_id]

        # 删除 Qdrant 点
        if qdrant_ids:
            try:
                from qdrant_client.models import PointIdsList
                self.qdrant.client.delete(
                    collection_name=collection,
                    points_selector=PointIdsList(points=qdrant_ids),
                )
            except Exception as e:
                logger.warning("Qdrant 删除失败，继续处理", error=str(e))

        # 删除 MySQL 记录
        await self.db.execute(
            delete(RetrievalSegment).where(
                and_(
                    RetrievalSegment.entity_type == entity_type,
                    RetrievalSegment.entity_id.in_(entity_ids),
                )
            )
        )

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

    @staticmethod
    def _build_sparse_text(title: str, content: str, topic_terms: Optional[List[str]]) -> str:
        """构建稀疏检索文本：标题 + 主题术语 + 内容前 500 字"""
        parts = [title]
        if topic_terms:
            parts.extend(topic_terms)
        if content:
            parts.append(content[:500])
        return " ".join(parts)
