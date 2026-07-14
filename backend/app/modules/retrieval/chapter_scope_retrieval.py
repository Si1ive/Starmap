"""沿标准章节树扩展范围，并通过关联表召回题目和知识点。"""

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    CanonicalChapter,
    KnowledgePoint,
    KnowledgePointChapterLink,
    Question,
    QuestionChapterLink,
)


async def expand_chapter_scope(
    db: AsyncSession,
    chapter_ids: List[str],
    upward_levels: int = 1,
) -> List[str]:
    """
    收集起点章节的兄弟与父章节，并按 upward_levels 继续向上扩展。
    """
    result = set(chapter_ids)
    chapters = (
        await db.execute(
            select(CanonicalChapter).where(
                CanonicalChapter.id.in_(chapter_ids),
                CanonicalChapter.status == "active",
            )
        )
    ).scalars().all()
    if not chapters:
        return list(result)

    parent_ids = {chapter.parent_id for chapter in chapters if chapter.parent_id}
    if parent_ids:
        siblings = (
            await db.execute(
                select(CanonicalChapter.id).where(
                    CanonicalChapter.parent_id.in_(parent_ids),
                    CanonicalChapter.status == "active",
                )
            )
        ).scalars().all()
        result.update(siblings)
        result.update(parent_ids)

    if upward_levels <= 0:
        return list(result)

    current_parents = parent_ids
    visited_parents = set(current_parents)
    for _ in range(upward_levels):
        if not current_parents:
            break

        parents = (
            await db.execute(
                select(CanonicalChapter).where(
                    CanonicalChapter.id.in_(list(current_parents)),
                    CanonicalChapter.status == "active",
                )
            )
        ).scalars().all()

        next_parent_ids = set()
        for parent in parents:
            result.add(parent.id)
            if parent.parent_id and parent.parent_id not in visited_parents:
                next_parent_ids.add(parent.parent_id)
                visited_parents.add(parent.parent_id)

        if next_parent_ids:
            cousins = (
                await db.execute(
                    select(CanonicalChapter.id).where(
                        CanonicalChapter.parent_id.in_(list(next_parent_ids)),
                        CanonicalChapter.status == "active",
                    )
                )
            ).scalars().all()
            result.update(cousins)

        current_parents = next_parent_ids

    return list(result)


async def retrieve_by_chapters(
    db: AsyncSession,
    chapter_ids: List[str],
    expand_to_siblings: bool = True,
    expand_upward_levels: int = 1,
    exclude_question_id: Optional[str] = None,
) -> Dict[str, Any]:
    """从章节范围内按关联表加载题目、知识点和章节摘要。"""
    primary_ids = list(dict.fromkeys(chapter_ids))
    all_chapter_ids = set(primary_ids)
    if expand_to_siblings and primary_ids:
        expanded = await expand_chapter_scope(
            db,
            primary_ids,
            expand_upward_levels,
        )
        all_chapter_ids.update(expanded)
    chapter_id_list = list(all_chapter_ids)

    question_rows = []
    knowledge_point_rows = []
    chapters = []
    if chapter_id_list:
        question_conditions = [
            QuestionChapterLink.canonical_chapter_id.in_(chapter_id_list),
            Question.status == "active",
        ]
        if exclude_question_id:
            question_conditions.append(Question.id != exclude_question_id)
        question_rows = (
            await db.execute(
                select(
                    Question,
                    QuestionChapterLink.canonical_chapter_id,
                )
                .join(
                    QuestionChapterLink,
                    QuestionChapterLink.question_id == Question.id,
                )
                .where(*question_conditions)
            )
        ).all()

        knowledge_point_rows = (
            await db.execute(
                select(
                    KnowledgePoint,
                    KnowledgePointChapterLink.canonical_chapter_id,
                )
                .join(
                    KnowledgePointChapterLink,
                    KnowledgePointChapterLink.knowledge_point_id
                    == KnowledgePoint.id,
                )
                .where(
                    KnowledgePointChapterLink.canonical_chapter_id.in_(
                        chapter_id_list
                    ),
                    KnowledgePoint.status == "active",
                )
            )
        ).all()

        chapters = (
            await db.execute(
                select(CanonicalChapter).where(
                    CanonicalChapter.id.in_(chapter_id_list),
                    CanonicalChapter.status == "active",
                )
            )
        ).scalars().all()

    questions_by_chapter: Dict[str, List[Dict[str, Any]]] = {}
    question_ids_by_chapter: Dict[str, set[str]] = {}
    for question, chapter_id in question_rows:
        seen_ids = question_ids_by_chapter.setdefault(chapter_id, set())
        if question.id in seen_ids:
            continue
        seen_ids.add(question.id)
        questions_by_chapter.setdefault(chapter_id, []).append(
            {
                "id": question.id,
                "content": (question.content or "")[:200],
                "question_no": getattr(question, "question_no", None),
                "exam_year": getattr(question, "exam_year", None),
            }
        )

    knowledge_points_by_chapter: Dict[str, List[Dict[str, Any]]] = {}
    knowledge_ids_by_chapter: Dict[str, set[str]] = {}
    for knowledge_point, chapter_id in knowledge_point_rows:
        seen_ids = knowledge_ids_by_chapter.setdefault(chapter_id, set())
        if knowledge_point.id in seen_ids:
            continue
        seen_ids.add(knowledge_point.id)
        knowledge_points_by_chapter.setdefault(chapter_id, []).append(
            {
                "id": knowledge_point.id,
                "title": knowledge_point.title,
                "summary": getattr(knowledge_point, "summary", None),
            }
        )

    return {
        "primary_chapters": [
            {
                "id": chapter.id,
                "name": chapter.name,
                "level": chapter.level,
            }
            for chapter in chapters
            if chapter.id in primary_ids
        ],
        "all_chapters": [
            {
                "id": chapter.id,
                "name": chapter.name,
                "level": chapter.level,
                "outline_code": chapter.outline_code,
            }
            for chapter in chapters
        ],
        "questions_by_chapter": questions_by_chapter,
        "knowledge_points_by_chapter": knowledge_points_by_chapter,
    }


async def retrieve_by_question(
    db: AsyncSession,
    question_id: str,
    expand_to_siblings: bool = True,
    expand_upward_levels: int = 1,
) -> Dict[str, Any]:
    """读取题目的直接章节关联，再委托章节范围召回。"""
    chapter_ids = (
        await db.execute(
            select(QuestionChapterLink.canonical_chapter_id).where(
                QuestionChapterLink.question_id == question_id
            )
        )
    ).scalars().all()

    return await retrieve_by_chapters(
        db,
        chapter_ids=list(dict.fromkeys(chapter_ids)),
        expand_to_siblings=expand_to_siblings,
        expand_upward_levels=expand_upward_levels,
        exclude_question_id=question_id,
    )
