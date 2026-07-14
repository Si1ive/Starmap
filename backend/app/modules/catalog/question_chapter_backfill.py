"""历史题目标准章节归属回填工作流。"""

from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import Question
from app.modules.catalog.chapter_compat import resolve_legacy_chapter_id

ChapterResolver = Callable[..., Awaitable[Optional[Dict[str, Any]]]]


class QuestionChapterBackfillService:
    """Resolve and update canonical chapters for historical questions."""

    def __init__(
        self,
        db: AsyncSession,
        chapter_resolver: ChapterResolver,
    ):
        self.db = db
        self.chapter_resolver = chapter_resolver

    async def backfill(
        self,
        review_status: str = "pending",
        status: str = "active",
        subject_id: Optional[str] = None,
        limit: int = 500,
        force: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        query = select(Question).where(Question.status != "deleted")
        if review_status:
            query = query.where(Question.review_status == review_status)
        if status:
            query = query.where(Question.status == status)
        if subject_id:
            query = query.where(Question.subject_id == subject_id)
        query = query.order_by(
            Question.created_at.desc(),
            Question.id.desc(),
        ).limit(limit)

        questions = (await self.db.execute(query)).scalars().all()
        result: Dict[str, Any] = {
            "scanned": len(questions),
            "updated": 0,
            "unchanged": 0,
            "skipped_existing": 0,
            "missed": 0,
            "failed": 0,
            "dry_run": dry_run,
            "items": [],
        }

        for question in questions:
            if question.primary_chapter_id and not force:
                result["skipped_existing"] += 1
                continue

            try:
                resolved = await self.chapter_resolver(
                    title=(question.content or "")[:200],
                    content=question.content or "",
                    subject_id=question.subject_id,
                    topic_terms=question.topic_terms or [],
                    entity_type="question",
                    options=question.options or [],
                )
            except Exception as exc:
                result["failed"] += 1
                result["items"].append(
                    {
                        "id": question.id,
                        "status": "failed",
                        "error": str(exc)[:300],
                    }
                )
                continue

            if not resolved:
                result["missed"] += 1
                result["items"].append(
                    {
                        "id": question.id,
                        "status": "missed",
                        "old_primary_chapter_id": (
                            question.primary_chapter_id
                        ),
                    }
                )
                continue

            await self._apply_resolved_chapter(
                question,
                resolved,
                result,
                dry_run=dry_run,
            )

        if not dry_run:
            await self.db.commit()

        return result

    async def _apply_resolved_chapter(
        self,
        question: Question,
        resolved: Dict[str, Any],
        result: Dict[str, Any],
        *,
        dry_run: bool,
    ) -> None:
        new_primary_chapter_id = resolved["chapter_id"]
        new_subject_id = resolved.get("subject_id") or question.subject_id
        legacy_chapter_id = await resolve_legacy_chapter_id(
            self.db,
            canonical_chapter_id=new_primary_chapter_id,
            subject_id=new_subject_id,
        )
        changed = (
            question.primary_chapter_id != new_primary_chapter_id
            or question.subject_id != new_subject_id
            or (
                legacy_chapter_id
                and question.chapter_id != legacy_chapter_id
            )
        )

        result["items"].append(
            {
                "id": question.id,
                "status": "updated" if changed else "unchanged",
                "old_subject_id": question.subject_id,
                "new_subject_id": new_subject_id,
                "old_primary_chapter_id": question.primary_chapter_id,
                "new_primary_chapter_id": new_primary_chapter_id,
                "old_chapter_id": question.chapter_id,
                "new_chapter_id": legacy_chapter_id,
                "source": resolved.get("source"),
                "confidence": resolved.get("confidence"),
            }
        )

        if not changed:
            result["unchanged"] += 1
            return

        result["updated"] += 1
        if dry_run:
            return

        question.subject_id = new_subject_id
        question.primary_chapter_id = new_primary_chapter_id
        if legacy_chapter_id:
            question.chapter_id = legacy_chapter_id
