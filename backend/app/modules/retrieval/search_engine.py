"""基础检索过滤、稀疏召回、命中合并与结果补全。"""

import json
from typing import Any, Dict, List, Optional

from qdrant_client.models import Filter, FieldCondition, MatchAny, MatchValue
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.qdrant import QdrantManager
from app.models.mysql_models import (
    Document,
    KnowledgePoint,
    Question,
    RetrievalSegment,
)


class RetrievalResult:
    """单条检索结果。"""

    def __init__(
        self,
        segment_id: str,
        entity_type: str,
        entity_id: str,
        segment_type: str,
        content_text: str,
        context_text: Optional[str],
        score: float,
        subject_id: Optional[str] = None,
        chapter_ids: Optional[List[str]] = None,
        source_document_id: Optional[str] = None,
        source_filename: Optional[str] = None,
        page_no: Optional[int] = None,
        title: Optional[str] = None,
        review_status: Optional[str] = None,
        status: Optional[str] = None,
        entity_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.segment_id = segment_id
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.segment_type = segment_type
        self.content_text = content_text
        self.context_text = context_text
        self.score = score
        self.subject_id = subject_id
        self.chapter_ids = chapter_ids or []
        self.source_document_id = source_document_id
        self.source_filename = source_filename
        self.page_no = page_no
        self.title = title
        self.review_status = review_status
        self.status = status
        self.entity_metadata = entity_metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        question_meta = (
            dict(self.entity_metadata)
            if self.entity_type == "question"
            else None
        )
        knowledge_point_meta = (
            dict(self.entity_metadata)
            if self.entity_type == "knowledge_point"
            else None
        )
        return {
            "segment_id": self.segment_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "segment_type": self.segment_type,
            "title": self.title,
            "content_text": self.content_text,
            "context_text": self.context_text,
            "score": self.score,
            "subject_id": self.subject_id,
            "chapter_ids": self.chapter_ids,
            "entity": {
                "id": self.entity_id,
                "type": self.entity_type,
                "title": self.title,
                "review_status": self.review_status,
                "status": self.status,
            },
            "source": {
                "document_id": self.source_document_id,
                "filename": self.source_filename,
                "page_no": self.page_no,
            },
            "question_meta": question_meta,
            "knowledge_point_meta": knowledge_point_meta,
        }


class RetrievalSearchEngine:
    """执行存储相关的检索步骤，不负责大纲与关系编排。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def build_filter(
        subject_id: Optional[str],
        chapter_ids: Optional[List[str]],
        filters: Optional[Dict[str, Any]] = None,
        *,
        knowledge_point_ids: Optional[List[str]] = None,
        exclude_entity_ids: Optional[List[str]] = None,
    ) -> Optional[Filter]:
        """构建 Qdrant 过滤条件。"""
        conditions = []
        must_not = []

        if subject_id:
            conditions.append(
                FieldCondition(
                    key="subject_id",
                    match=MatchValue(value=subject_id),
                )
            )

        if chapter_ids:
            conditions.append(
                FieldCondition(
                    key="chapter_ids",
                    match=MatchAny(any=chapter_ids),
                )
            )

        if knowledge_point_ids:
            conditions.append(
                FieldCondition(
                    key="knowledge_point_ids",
                    match=MatchAny(any=knowledge_point_ids),
                )
            )

        structured_filters = filters or {}
        for key in (
            "exam_year",
            "exam_scope",
            "difficulty",
            "question_type",
            "answer_source",
        ):
            value = structured_filters.get(key)
            if value is not None and value != "":
                conditions.append(
                    FieldCondition(key=key, match=MatchValue(value=value))
                )

        tags = structured_filters.get("tags")
        if tags:
            conditions.append(
                FieldCondition(key="tags", match=MatchAny(any=list(tags)))
            )

        if exclude_entity_ids:
            must_not.append(
                FieldCondition(
                    key="entity_id",
                    match=MatchAny(any=exclude_entity_ids),
                )
            )

        return Filter(must=conditions or None, must_not=must_not or None) if (conditions or must_not) else None

    @staticmethod
    def get_collections(entity_type: Optional[str]) -> List[str]:
        """根据实体类型返回需要搜索的 collection。"""
        if entity_type == "knowledge_point":
            return [QdrantManager.COLLECTION_KNOWLEDGE_SEGMENTS]
        if entity_type == "question":
            return [QdrantManager.COLLECTION_QUESTION_SEGMENTS]
        return [
            QdrantManager.COLLECTION_KNOWLEDGE_SEGMENTS,
            QdrantManager.COLLECTION_QUESTION_SEGMENTS,
        ]

    async def sparse_search(
        self,
        collection: str,
        query: str,
        limit: int,
        subject_id: Optional[str] = None,
        chapter_ids: Optional[List[str]] = None,
        knowledge_point_ids: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        exclude_entity_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """使用 MySQL sparse_text 执行关键词召回。"""
        keywords = query.strip().split()
        if not keywords:
            return []

        entity_type = (
            "knowledge_point"
            if collection == QdrantManager.COLLECTION_KNOWLEDGE_SEGMENTS
            else "question"
        )
        conditions = self._build_sparse_conditions(
            entity_type=entity_type,
            subject_id=subject_id,
            chapter_ids=chapter_ids,
            knowledge_point_ids=knowledge_point_ids,
            filters=filters,
            exclude_entity_ids=exclude_entity_ids,
        )
        keyword_conditions = [
            RetrievalSegment.sparse_text.ilike(f"%{keyword}%")
            for keyword in keywords[:5]
        ]
        if keyword_conditions:
            conditions.append(or_(*keyword_conditions))

        result = await self.db.execute(
            select(RetrievalSegment)
            .where(and_(*conditions))
            .limit(limit)
        )
        segments = result.scalars().all()

        hits = []
        for segment in segments:
            if not segment.qdrant_point_id:
                continue
            match_count = sum(
                1
                for keyword in keywords
                if keyword.lower() in (segment.sparse_text or "").lower()
            )
            hits.append(
                {
                    "id": segment.qdrant_point_id,
                    "score": match_count / max(len(keywords), 1),
                    "payload": {
                        "segment_id": segment.id,
                        "entity_id": segment.entity_id,
                        "segment_type": segment.segment_type,
                        "subject_id": segment.subject_id,
                        "chapter_ids": segment.chapter_ids or [],
                        "content_preview": segment.content_text[:200],
                    },
                }
            )
        return hits

    @staticmethod
    def merge_hits(
        dense_hits: List[Dict[str, Any]],
        sparse_hits: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """合并 dense 和 sparse 结果，按向量 0.7、关键词 0.3 加权。"""
        merged: Dict[str, Dict[str, Any]] = {}

        for hit in dense_hits:
            hit_copy = dict(hit)
            hit_id = str(hit_copy["id"])
            hit_copy["_dense_score"] = hit_copy["score"]
            merged[hit_id] = hit_copy

        for hit in sparse_hits:
            hit_id = str(hit["id"])
            if hit_id in merged:
                dense_score = merged[hit_id].get("_dense_score", 0)
                merged[hit_id]["score"] = 0.7 * dense_score + 0.3 * hit["score"]
            else:
                hit_copy = dict(hit)
                hit_copy["score"] = hit_copy["score"] * 0.8
                merged[hit_id] = hit_copy

        results = list(merged.values())
        results.sort(key=lambda item: item["score"], reverse=True)
        return results

    async def hydrate_results(
        self,
        hits: List[Dict[str, Any]],
    ) -> List[RetrievalResult]:
        """按命中顺序从 MySQL 补全 segment 与来源文档信息。"""
        if not hits:
            return []

        segment_ids = [
            hit["payload"].get("segment_id")
            for hit in hits
            if hit.get("payload", {}).get("segment_id")
        ]
        if not segment_ids:
            return []

        result = await self.db.execute(
            select(RetrievalSegment).where(RetrievalSegment.id.in_(segment_ids))
        )
        segments_by_id = {
            segment.id: segment
            for segment in result.scalars().all()
        }

        document_ids = list(
            {
                segment.document_id
                for segment in segments_by_id.values()
                if segment.document_id
            }
        )
        document_names: Dict[str, str] = {}
        if document_ids:
            document_result = await self.db.execute(
                select(Document).where(Document.id.in_(document_ids))
            )
            document_names = {
                document.id: self._document_source_name(document)
                for document in document_result.scalars().all()
            }
        knowledge_point_details = await self._load_knowledge_point_details(
            [
                segment.entity_id
                for segment in segments_by_id.values()
                if segment.entity_type == "knowledge_point"
            ]
        )
        question_details = await self._load_question_details(
            [
                segment.entity_id
                for segment in segments_by_id.values()
                if segment.entity_type == "question"
            ]
        )

        retrieval_results: List[RetrievalResult] = []
        for hit in hits:
            segment_id = hit.get("payload", {}).get("segment_id")
            segment = segments_by_id.get(segment_id)
            if not segment:
                continue
            entity_details = (
                question_details.get(segment.entity_id)
                if segment.entity_type == "question"
                else knowledge_point_details.get(segment.entity_id)
            ) or {}
            retrieval_results.append(
                RetrievalResult(
                    segment_id=segment.id,
                    entity_type=segment.entity_type,
                    entity_id=segment.entity_id,
                    segment_type=segment.segment_type,
                    content_text=segment.content_text,
                    context_text=segment.context_text,
                    score=hit["score"],
                    subject_id=segment.subject_id,
                    chapter_ids=segment.chapter_ids or [],
                    source_document_id=segment.document_id,
                    source_filename=document_names.get(segment.document_id),
                    page_no=segment.page_no,
                    title=entity_details.get("title"),
                    review_status=entity_details.get("review_status"),
                    status=entity_details.get("status"),
                    entity_metadata=entity_details.get("metadata"),
                )
            )
        return retrieval_results

    @staticmethod
    def _document_source_name(document: Document) -> Optional[str]:
        """优先使用展示来源，其次回退到文档标题。"""
        for value in (
            getattr(document, "source_label", None),
            getattr(document, "title", None),
        ):
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    async def _load_knowledge_point_details(
        self,
        knowledge_point_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        unique_ids = list(dict.fromkeys(knowledge_point_ids))
        if not unique_ids:
            return {}

        result = await self.db.execute(
            select(KnowledgePoint).where(KnowledgePoint.id.in_(unique_ids))
        )
        return {
            knowledge_point.id: {
                "title": knowledge_point.title,
                "review_status": knowledge_point.review_status,
                "status": knowledge_point.status,
                "metadata": {
                    "difficulty": knowledge_point.difficulty,
                    "exam_frequency": knowledge_point.exam_frequency,
                    "source": knowledge_point.source,
                    "source_page": knowledge_point.source_page,
                    "review_status": knowledge_point.review_status,
                    "status": knowledge_point.status,
                    "aliases": knowledge_point.aliases or [],
                    "tags": knowledge_point.tags or [],
                },
            }
            for knowledge_point in result.scalars().all()
        }

    async def _load_question_details(
        self,
        question_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        unique_ids = list(dict.fromkeys(question_ids))
        if not unique_ids:
            return {}

        result = await self.db.execute(
            select(Question).where(Question.id.in_(unique_ids))
        )
        return {
            question.id: {
                "title": self._question_title(question),
                "review_status": question.review_status,
                "status": question.status,
                "metadata": {
                    "question_type": question.type,
                    "difficulty": question.difficulty,
                    "source": question.source,
                    "paper_name": question.paper_name,
                    "question_no": question.question_no,
                    "exam_year": question.exam_year,
                    "exam_scope": question.exam_scope,
                    "answer_source": question.answer_source,
                    "review_status": question.review_status,
                    "status": question.status,
                    "knowledge_point_ids": question.knowledge_point_ids or [],
                    "tags": question.tags or [],
                },
            }
            for question in result.scalars().all()
        }

    @staticmethod
    def _question_title(question: Question) -> str:
        title = (question.content or "").strip()
        if question.question_no:
            return f"[{question.question_no}] {title}"
        return title

    @staticmethod
    def _build_sparse_conditions(
        entity_type: str,
        subject_id: Optional[str],
        chapter_ids: Optional[List[str]],
        knowledge_point_ids: Optional[List[str]],
        filters: Optional[Dict[str, Any]],
        exclude_entity_ids: Optional[List[str]],
    ) -> List[ColumnElement[bool]]:
        """构建与 Qdrant payload filter 等价的 MySQL 条件。"""
        conditions: List[ColumnElement[bool]] = [
            RetrievalSegment.entity_type == entity_type,
        ]

        if subject_id:
            conditions.append(RetrievalSegment.subject_id == subject_id)

        if chapter_ids:
            conditions.append(
                func.json_overlaps(
                    RetrievalSegment.chapter_ids,
                    json.dumps(chapter_ids),
                )
                == 1
            )

        if knowledge_point_ids:
            conditions.append(
                or_(
                    RetrievalSegment.entity_id.in_(knowledge_point_ids),
                    func.json_overlaps(
                        func.json_extract(
                            RetrievalSegment.metadata_json,
                            "$.knowledge_point_ids",
                        ),
                        json.dumps(knowledge_point_ids),
                    )
                    == 1,
                )
            )

        structured_filters = filters or {}
        for key in (
            "exam_year",
            "exam_scope",
            "difficulty",
            "question_type",
            "answer_source",
        ):
            value = structured_filters.get(key)
            if value is None or value == "":
                continue
            conditions.append(
                func.json_unquote(
                    func.json_extract(
                        RetrievalSegment.metadata_json,
                        f"$.{key}",
                    )
                )
                == str(value)
            )

        tags = structured_filters.get("tags")
        if tags:
            conditions.append(
                func.json_overlaps(
                    func.json_extract(
                        RetrievalSegment.metadata_json,
                        "$.tags",
                    ),
                    json.dumps(list(tags)),
                )
                == 1
            )

        if exclude_entity_ids:
            conditions.append(~RetrievalSegment.entity_id.in_(exclude_entity_ids))

        return conditions
