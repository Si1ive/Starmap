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
from app.modules.monitoring.vector_recalls import VectorRecallRecorder


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
    recall_context: Dict[str, Any] | None = None,
) -> OutlineExpansionResult:
    """
    使用标准章节标题和内容向量扩展查询，并提取学科、章节过滤条件。

    标题命中使用 1.2 权重；低于 0.7 的章节不参与扩展。
    """
    if not query.strip():
        return OutlineExpansionResult(expanded_query=query)

    embedding = await get_embedding_service_from_settings(db)
    query_vector = await embedding.embed_text(query)

    try:
        title_hits = _search_chapter_segments(
            query_vector, segment_type="title", limit=top_k * 2
        )
    except Exception as exc:
        await _persist_outline_error(query, recall_context, "title", exc)
        raise
    try:
        content_hits = _search_chapter_segments(
            query_vector, segment_type="content", limit=top_k * 2
        )
    except Exception as exc:
        await _persist_outline_error(query, recall_context, "content", exc)
        raise

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
        await _persist_outline_recalls(
            query=query,
            recall_context=recall_context,
            title_hits=title_hits,
            content_hits=content_hits,
            chapter_titles={},
        )
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

    await _persist_outline_recalls(
        query=query,
        recall_context=recall_context,
        title_hits=title_hits,
        content_hits=content_hits,
        chapter_titles={chapter_id: chapter.name for chapter_id, chapter in chapter_map.items()},
    )

    # 大纲命中只负责收窄结构化范围，并用最高分章节名补足短查询语义。
    # 禁止把多个章节的 keywords/enhanced_description 串成超长 dense query；
    # 那会把一个具体问题稀释成整章概览，也会让监控入参失去可读性。
    query_parts = [query]
    subject_ids: List[str] = []
    matched_chapters: List[Dict[str, Any]] = []
    for chapter_id, score in top_chapters:
        chapter = chapter_map.get(chapter_id)
        if not chapter:
            continue
        if not matched_chapters and chapter.name.strip() not in query:
            query_parts.append(chapter.name.strip())
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
        expanded_query=" ".join(query_parts)[:200],
        subject_ids=subject_ids,
        chapter_ids=top_ids,
        matched_chapters=matched_chapters,
    )


async def _persist_outline_recalls(
    *,
    query: str,
    recall_context: Dict[str, Any] | None,
    title_hits: List[Dict[str, Any]],
    content_hits: List[Dict[str, Any]],
    chapter_titles: Dict[str, str],
) -> None:
    if not recall_context:
        return
    for segment_type, hits in (("title", title_hits), ("content", content_hits)):
        recorder = VectorRecallRecorder(
            called_by=recall_context.get("called_by", "retrieval_service"),
            purpose="大纲章节向量召回",
            query_text=query,
            trace_id=recall_context.get("trace_id"),
            run_id=recall_context.get("run_id"),
            activity_id=recall_context.get("activity_id"),
            attempt_id=recall_context.get("attempt_id"),
            phase=f"outline_{segment_type}",
            collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
            query_kind="raw",
            raw_query_text=query,
        ).start()
        recorder.record_qdrant_results(
            hits,
            collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
            title_by_entity_id=chapter_titles,
        )
        await recorder.persist()


async def _persist_outline_error(
    query: str,
    recall_context: Dict[str, Any] | None,
    segment_type: str,
    exc: Exception,
) -> None:
    if not recall_context:
        return
    recorder = VectorRecallRecorder(
        called_by=recall_context.get("called_by", "retrieval_service"),
        purpose="大纲章节向量召回",
        query_text=query,
        trace_id=recall_context.get("trace_id"),
        run_id=recall_context.get("run_id"),
        activity_id=recall_context.get("activity_id"),
        attempt_id=recall_context.get("attempt_id"),
        phase=f"outline_{segment_type}",
        collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
        query_kind="raw",
        raw_query_text=query,
    ).start()
    recorder.record_error(exc)
    await recorder.persist()


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
