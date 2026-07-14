"""Structured corpus content overview query service."""

from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    CanonicalChapter,
    Document,
    EntityExtractionRun,
    KnowledgePoint,
    Question,
)
from app.modules.corpus.quality_gate import CorpusQualityGateBuilder


class CorpusContentOverviewService:
    """Load extracted entities and compose the corpus content overview."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, document_id: str) -> Optional[Dict[str, Any]]:
        document = (
            await self.db.execute(
                select(Document).where(Document.id == document_id)
            )
        ).scalar_one_or_none()
        if not document:
            return None

        knowledge_points = (
            await self.db.execute(
                select(KnowledgePoint)
                .where(
                    KnowledgePoint.source_document_id == document_id,
                    KnowledgePoint.status != "deleted",
                )
                .order_by(KnowledgePoint.created_at, KnowledgePoint.id)
            )
        ).scalars().all()
        questions = (
            await self.db.execute(
                select(Question).where(
                    Question.source_document_id == document_id,
                    Question.status != "deleted",
                )
            )
        ).scalars().all()
        latest_run = (
            await self.db.execute(
                select(EntityExtractionRun)
                .where(
                    EntityExtractionRun.document_id == document_id,
                    EntityExtractionRun.scope == "document",
                )
                .order_by(EntityExtractionRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        entity_runs = (
            await self.db.execute(
                select(EntityExtractionRun)
                .where(
                    EntityExtractionRun.document_id == document_id,
                    EntityExtractionRun.scope == "entity",
                )
                .order_by(EntityExtractionRun.created_at.desc())
            )
        ).scalars().all()
        latest_entity_run_map = self.build_latest_entity_run_map(entity_runs)

        chapter_ids = {
            item.primary_chapter_id
            for item in [*knowledge_points, *questions]
            if item.primary_chapter_id
        }
        chapter_map: Dict[str, CanonicalChapter] = {}
        if chapter_ids:
            chapters = (
                await self.db.execute(
                    select(CanonicalChapter).where(
                        CanonicalChapter.id.in_(list(chapter_ids))
                    )
                )
            ).scalars().all()
            chapter_map = {chapter.id: chapter for chapter in chapters}

        groups: Dict[str, Dict[str, Any]] = {}
        ungrouped_knowledge_points: List[Dict[str, Any]] = []
        for knowledge_point in knowledge_points:
            brief = {
                "id": knowledge_point.id,
                "title": knowledge_point.title,
                "summary": knowledge_point.summary,
                "content_preview": (knowledge_point.content or "")[:300],
                "topic_terms": knowledge_point.topic_terms or [],
                "review_status": knowledge_point.review_status,
                "status": knowledge_point.status,
                "source_section_path": knowledge_point.source_section_path,
                "reextraction": latest_entity_run_map.get(
                    ("knowledge_point", knowledge_point.id)
                ),
            }
            chapter_id = knowledge_point.primary_chapter_id
            if chapter_id and chapter_id in chapter_map:
                if chapter_id not in groups:
                    chapter = chapter_map[chapter_id]
                    groups[chapter_id] = {
                        "chapter_id": chapter_id,
                        "chapter_name": chapter.name,
                        "outline_code": chapter.outline_code,
                        "keywords": chapter.keywords or [],
                        "description": chapter.description,
                        "exam_guidance": chapter.exam_guidance,
                        "knowledge_points": [],
                    }
                groups[chapter_id]["knowledge_points"].append(brief)
            else:
                ungrouped_knowledge_points.append(brief)

        questions_sorted = sorted(questions, key=self._question_sort_key)
        question_items = [
            {
                "id": question.id,
                "question_no": question.question_no,
                "type": question.type,
                "content_preview": (question.content or "")[:300],
                "options": question.options or [],
                "exam_year": question.exam_year,
                "review_status": question.review_status,
                "status": question.status,
                "primary_chapter_id": question.primary_chapter_id,
                "primary_chapter_name": (
                    chapter_map[question.primary_chapter_id].name
                    if question.primary_chapter_id
                    and question.primary_chapter_id in chapter_map
                    else None
                ),
                "source_section_path": question.source_section_path,
                "is_unassigned": self._is_question_unassigned(question),
                "extraction_meta": question.extraction_meta or None,
                "reextraction": latest_entity_run_map.get(
                    ("question", question.id)
                ),
            }
            for question in questions_sorted
        ]
        unassigned_question_count = sum(
            1 for question in questions if self._is_question_unassigned(question)
        )

        summary = {
            "knowledge_count": len(knowledge_points),
            "question_count": len(questions),
            "chapter_count": len(groups),
            "ungrouped_count": len(ungrouped_knowledge_points),
            "unassigned_question_count": unassigned_question_count,
        }
        return {
            "document_id": document.id,
            "title": document.title,
            "doc_type": document.doc_type,
            "knowledge_chapters": list(groups.values()),
            "ungrouped_knowledge_points": ungrouped_knowledge_points,
            "questions": question_items,
            "summary": summary,
            "quality_gate": CorpusQualityGateBuilder.build(
                document=document,
                knowledge_points=knowledge_points,
                questions=questions,
                summary=summary,
                latest_run=latest_run,
            ),
        }

    @staticmethod
    def _question_sort_key(question: Question) -> tuple:
        number = (question.question_no or "").strip()
        digits = "".join(character for character in number if character.isdigit())
        return (0, int(digits)) if digits else (1, number)

    @staticmethod
    def _is_question_unassigned(question: Question) -> bool:
        return not question.subject_id or not question.chapter_id

    @classmethod
    def build_latest_entity_run_map(
        cls,
        runs: Sequence[EntityExtractionRun],
    ) -> Dict[tuple, Dict[str, Any]]:
        """Keep the newest durable task state for each entity target."""
        result: Dict[tuple, Dict[str, Any]] = {}
        for run in runs:
            key = (run.target_entity_type, run.target_entity_id)
            if not all(key) or key in result:
                continue
            result[key] = cls._serialize_entity_run(run)
        return result

    @staticmethod
    def _serialize_entity_run(
        run: EntityExtractionRun,
    ) -> Dict[str, Any]:
        return {
            "id": run.id,
            "status": run.status,
            "scope": run.scope,
            "target_entity_type": run.target_entity_type,
            "target_entity_id": run.target_entity_id,
            "error_detail": run.error_detail,
            "result": run.result_json,
            "started_at": (
                run.started_at.isoformat() if run.started_at else None
            ),
            "completed_at": (
                run.completed_at.isoformat() if run.completed_at else None
            ),
        }
