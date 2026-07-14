"""利用标准章节向量扩展短查询并生成结构化过滤条件。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.qdrant import qdrant_manager
from app.infrastructure.ai.embedding_service import (
    get_embedding_service_from_settings,
)
from app.models.mysql_models import CanonicalChapter


@dataclass
class OutlineExpansionResult:
    """大纲查询扩展结果。"""

    expanded_query: str
    subject_ids: List[str] = field(default_factory=list)
    chapter_ids: List[str] = field(default_factory=list)
    matched_chapters: List[Dict[str, Any]] = field(default_factory=list)


async def expand_query_with_outline(
    db: AsyncSession,
    query: str,
    top_k: int = 3,
) -> OutlineExpansionResult:
    """
    使用标准章节标题和内容向量扩展查询，并提取学科、章节过滤条件。

    标题命中使用 1.2 权重；低于 0.7 的章节不参与扩展。
    """
    if not query.strip():
        return OutlineExpansionResult(expanded_query=query)

    embedding = await get_embedding_service_from_settings(db)
    query_vector = await embedding.embed_text(query)

    title_hits = _search_chapter_segments(
        query_vector,
        segment_type="title",
        limit=top_k * 2,
    )
    content_hits = _search_chapter_segments(
        query_vector,
        segment_type="content",
        limit=top_k * 2,
    )

    chapter_scores: Dict[str, float] = {}
    for hit in title_hits + content_hits:
        payload = hit.get("payload") or {}
        chapter_id = payload.get("entity_id")
        if not chapter_id:
            continue
        weight = 1.2 if payload.get("segment_type") == "title" else 1.0
        score = hit.get("score", 0) * weight
        chapter_scores[chapter_id] = max(
            chapter_scores.get(chapter_id, 0),
            score,
        )

    top_chapters = sorted(
        [
            (chapter_id, score)
            for chapter_id, score in chapter_scores.items()
            if score >= 0.7
        ],
        key=lambda item: -item[1],
    )[:top_k]
    if not top_chapters:
        return OutlineExpansionResult(expanded_query=query)

    top_ids = [chapter_id for chapter_id, _ in top_chapters]
    chapters = (
        await db.execute(
            select(CanonicalChapter).where(
                CanonicalChapter.id.in_(top_ids)
            )
        )
    ).scalars().all()
    chapter_map = {chapter.id: chapter for chapter in chapters}

    query_parts = [query]
    subject_ids: List[str] = []
    matched_chapters: List[Dict[str, Any]] = []
    for chapter_id, score in top_chapters:
        chapter = chapter_map.get(chapter_id)
        if not chapter:
            continue
        if chapter.keywords:
            query_parts.append(" ".join(chapter.keywords[:8]))
        if chapter.enhanced_description:
            query_parts.append(chapter.enhanced_description[:100])
        if chapter.subject_id and chapter.subject_id not in subject_ids:
            subject_ids.append(chapter.subject_id)
        matched_chapters.append(
            {
                "chapter_id": chapter_id,
                "name": chapter.name,
                "outline_code": chapter.outline_code,
                "score": round(score, 4),
                "keywords": chapter.keywords,
            }
        )

    return OutlineExpansionResult(
        expanded_query=" ".join(query_parts)[:2000],
        subject_ids=subject_ids,
        chapter_ids=top_ids,
        matched_chapters=matched_chapters,
    )


def _search_chapter_segments(
    query_vector: List[float],
    *,
    segment_type: str,
    limit: int,
) -> List[Dict[str, Any]]:
    return qdrant_manager.search(
        collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
        query_vector=query_vector,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="entity_type",
                    match=MatchValue(value="canonical_chapter"),
                ),
                FieldCondition(
                    key="segment_type",
                    match=MatchValue(value=segment_type),
                ),
            ]
        ),
        limit=limit,
    )
