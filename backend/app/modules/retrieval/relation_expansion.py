"""检索结果的知识关系与关联题目扩展。"""

from typing import Any, Dict, List

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    KnowledgePoint,
    KnowledgeRelation,
    Question,
    QuestionKnowledgeLink,
    RetrievalSegment,
)
from app.modules.retrieval.search_engine import RetrievalResult

logger = get_logger(__name__)


class RetrievalRelationExpander:
    """根据主检索知识点补充关系边、关联知识点和题目。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def expand(
        self,
        primary_ids: List[str],
        limit: int,
    ) -> Dict[str, Any]:
        relations = await self._get_relations(primary_ids)
        primary_id_set = set(primary_ids)
        related_ids = list(
            dict.fromkeys(
                relation["related_knowledge_id"]
                for relation in relations
                if relation["related_knowledge_id"] not in primary_id_set
            )
        )
        related_results = await self._get_related_results(related_ids, limit)

        linked_questions: List[Dict[str, Any]] = []
        try:
            linked_questions = await self._get_linked_questions(
                primary_ids,
                limit=limit,
            )
        except Exception as error:
            logger.warning("知识点关联题目扩展失败，跳过", error=str(error))

        return {
            "related_results": [
                result.to_dict()
                for result in related_results[:limit]
            ],
            "relations": relations[:10],
            "linked_questions": linked_questions,
        }

    async def _get_related_results(
        self,
        related_ids: List[str],
        limit: int,
    ) -> List[RetrievalResult]:
        if not related_ids:
            return []

        result = await self.db.execute(
            select(RetrievalSegment).where(
                and_(
                    RetrievalSegment.entity_type == "knowledge_point",
                    RetrievalSegment.entity_id.in_(related_ids),
                    RetrievalSegment.segment_type == "content",
                )
            )
        )
        segments = result.scalars().all()
        return [
            RetrievalResult(
                segment_id=segment.id,
                entity_type="knowledge_point",
                entity_id=segment.entity_id,
                segment_type=segment.segment_type,
                content_text=segment.content_text,
                context_text=segment.context_text,
                score=0.3,
                subject_id=segment.subject_id,
                chapter_ids=segment.chapter_ids or [],
                source_document_id=segment.document_id,
            )
            for segment in segments[:limit]
        ]

    async def _get_linked_questions(
        self,
        knowledge_point_ids: List[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        if not knowledge_point_ids:
            return []

        rows = (
            await self.db.execute(
                select(QuestionKnowledgeLink, Question)
                .join(
                    Question,
                    QuestionKnowledgeLink.question_id == Question.id,
                )
                .where(
                    QuestionKnowledgeLink.knowledge_point_id.in_(
                        knowledge_point_ids
                    ),
                    Question.status != "deleted",
                )
                .order_by(QuestionKnowledgeLink.relevance.desc())
                .limit(limit * 3)
            )
        ).all()

        seen_question_ids = set()
        linked_questions: List[Dict[str, Any]] = []
        for link, question in rows:
            if question.id in seen_question_ids:
                continue
            seen_question_ids.add(question.id)
            linked_questions.append(
                {
                    "question_id": question.id,
                    "content": (question.content or "")[:200],
                    "question_no": question.question_no,
                    "exam_year": question.exam_year,
                    "source": question.source,
                    "relevance": float(link.relevance or 0),
                    "via_knowledge_point_id": link.knowledge_point_id,
                }
            )
            if len(linked_questions) >= limit:
                break
        return linked_questions

    async def _get_relations(
        self,
        knowledge_point_ids: List[str],
    ) -> List[Dict[str, Any]]:
        result = await self.db.execute(
            select(KnowledgeRelation, KnowledgePoint)
            .join(
                KnowledgePoint,
                or_(
                    and_(
                        KnowledgeRelation.target_knowledge_id
                        == KnowledgePoint.id,
                        KnowledgeRelation.source_knowledge_id.in_(
                            knowledge_point_ids
                        ),
                    ),
                    and_(
                        KnowledgeRelation.source_knowledge_id
                        == KnowledgePoint.id,
                        KnowledgeRelation.target_knowledge_id.in_(
                            knowledge_point_ids
                        ),
                    ),
                ),
            )
            .where(
                KnowledgeRelation.review_status == "approved",
                or_(
                    KnowledgeRelation.source_knowledge_id.in_(
                        knowledge_point_ids
                    ),
                    KnowledgeRelation.target_knowledge_id.in_(
                        knowledge_point_ids
                    ),
                ),
            )
        )

        relations = []
        for relation, knowledge_point in result.all():
            if relation.source_knowledge_id in knowledge_point_ids:
                direction = "outgoing"
                related_id = relation.target_knowledge_id
            else:
                direction = "incoming"
                related_id = relation.source_knowledge_id

            relations.append(
                {
                    "relation_id": relation.id,
                    "relation_type": relation.relation_type,
                    "direction": direction,
                    "related_knowledge_id": related_id,
                    "related_knowledge_title": knowledge_point.title,
                    "evidence_text": relation.evidence_text,
                }
            )
        return relations
