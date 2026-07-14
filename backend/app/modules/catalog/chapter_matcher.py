"""Chapter keyword and vector matching strategies."""

from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CanonicalChapter

logger = get_logger(__name__)

HIGH_CONFIDENCE_KEYWORD_THRESHOLD = 0.85
VECTOR_MATCH_THRESHOLD = 0.55
SUBJECT_FALLBACK_MARGIN = 0.05

VectorSearchCore = Callable[[Any, str], Awaitable[List[Dict[str, Any]]]]


class ChapterMatcher:
    """Match corpus entities to canonical chapters."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def match_by_keyword(
        self,
        title: str,
        content: str,
        subject_id: Optional[str],
        topic_terms: List[str],
        include_content: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Match CanonicalChapter rows by name, aliases, keywords, and clean probes.

        Returns the best match with confidence >= 0.75, otherwise None.
        """
        if not (title or content or topic_terms):
            return None

        query = select(CanonicalChapter).where(CanonicalChapter.status == "active")
        if subject_id:
            query = query.where(CanonicalChapter.subject_id == subject_id)
        chapters = (await self.db.execute(query)).scalars().all()
        if not chapters:
            return None

        title_norm = (title or "").strip().lower()
        terms_norm = [t.strip().lower() for t in (topic_terms or []) if t and t.strip()]
        probes = [probe for probe in [title_norm, *terms_norm] if probe]
        content_l = (content or "").strip().lower() if include_content else ""
        if not probes and not content_l:
            return None

        best: Optional[Tuple[float, CanonicalChapter]] = None
        for chapter in chapters:
            name_l = (chapter.name or "").strip().lower()
            aliases_l = [(alias or "").strip().lower() for alias in (chapter.aliases or []) if alias]
            keywords_l = [
                (keyword or "").strip().lower()
                for keyword in (chapter.keywords or [])
                if keyword
            ]

            score = 0.0
            for probe in probes:
                if len(probe) < 2:
                    continue
                if name_l and probe == name_l:
                    score = max(score, 1.0)
                elif probe in aliases_l:
                    score = max(score, 0.9)
                elif probe in keywords_l:
                    score = max(score, 0.88)
                elif name_l and len(probe) >= 3 and probe in name_l:
                    score = max(score, 0.8)

            specific_keywords = {keyword for keyword in keywords_l if len(keyword) >= 3}
            if name_l and len(name_l) >= 4:
                specific_keywords.add(name_l)
            for alias in aliases_l:
                if len(alias) >= 3:
                    specific_keywords.add(alias)

            hits = {keyword for keyword in specific_keywords if keyword in content_l}
            if hits:
                strong_hits = {keyword for keyword in hits if len(keyword) >= 4}
                if len(hits) >= 2:
                    score = max(score, min(0.78 + 0.04 * len(hits), 0.9))
                elif strong_hits:
                    score = max(score, 0.78)

            if best is None or score > best[0]:
                best = (score, chapter)

        if not best or best[0] < 0.75:
            return None

        score, chapter = best
        return {
            "chapter_id": chapter.id,
            "subject_id": chapter.subject_id,
            "confidence": round(score, 4),
            "source": "keyword_match",
        }

    async def match_by_vector_search(
        self,
        entity: Any,
        entity_type: str,
        search_core: Optional[VectorSearchCore] = None,
    ) -> List[Dict[str, Any]]:
        """Search canonical chapter segments and record the vector recall."""
        from app.services.vector_recall_recorder import VectorRecallRecorder

        if entity_type == "knowledge_point":
            query_text = (
                f"{getattr(entity, 'title', '') or ''}\n"
                f"{(getattr(entity, 'content', '') or '')[:500]}"
            )
        else:
            query_text = (getattr(entity, "content", "") or "")[:300]

        recorder = VectorRecallRecorder(
            called_by=entity_type,
            purpose="章节归属向量召回",
            query_text=query_text,
            query_entity_id=getattr(entity, "id", None),
            subject_id=getattr(entity, "subject_id", None),
        ).start()

        try:
            candidates = await (search_core or self.vector_search_core)(entity, entity_type)
        except Exception as exc:
            recorder.record_error(exc)
            await recorder.persist()
            raise

        chapter_name_map: Dict[str, str] = {}
        try:
            for candidate in candidates:
                chapter_id = candidate.get("chapter_id")
                if chapter_id and chapter_id not in chapter_name_map:
                    chapter = await self.db.get(CanonicalChapter, chapter_id)
                    if chapter:
                        chapter_name_map[chapter_id] = chapter.name
        except Exception:
            chapter_name_map = {}

        recorder.record_results(
            candidates,
            threshold=VECTOR_MATCH_THRESHOLD,
            chapter_name_map=chapter_name_map,
        )
        await recorder.persist()
        return candidates

    async def vector_search_core(
        self,
        entity: Any,
        entity_type: str,
    ) -> List[Dict[str, Any]]:
        """Search canonical chapter segments and return at most three matches."""
        from app.db.qdrant import qdrant_manager
        from app.services.embedding_service import get_embedding_service_from_settings
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        if entity_type == "knowledge_point":
            query_texts = [f"{entity.title}\n{(entity.content or '')[:500]}"]
        else:
            options_text = "\n".join(
                f"{option.get('key', '')}. {option.get('text', '')}"
                for option in (entity.options or [])[:4]
            )
            stem_text = entity.content[:300]
            query_texts = [stem_text]
            if options_text.strip():
                query_texts.append(f"{stem_text}\n{options_text[:200]}")

        query_texts = [text for text in query_texts if text.strip()]
        if not query_texts:
            return []

        try:
            embedding_service = await get_embedding_service_from_settings(self.db)
            if len(query_texts) == 1:
                query_vectors = [await embedding_service.embed_text(query_texts[0])]
            else:
                query_vectors = await embedding_service.embed_batch(query_texts)
        except Exception as exc:
            logger.error("生成 embedding 失败", error=str(exc))
            return []

        def build_filter(filter_subject_id: Optional[str] = None) -> Filter:
            must = [
                FieldCondition(
                    key="entity_type",
                    match=MatchValue(value="canonical_chapter"),
                ),
            ]
            if filter_subject_id:
                must.append(
                    FieldCondition(
                        key="subject_id",
                        match=MatchValue(value=filter_subject_id),
                    )
                )
            return Filter(must=must)

        def aggregate(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            chapter_scores: Dict[str, Dict[str, Any]] = {}
            for hit in results:
                payload = hit.get("payload") or {}
                chapter_id = payload.get("entity_id")
                if not chapter_id:
                    continue
                score = hit.get("score", 0)
                current = chapter_scores.get(chapter_id)
                if not current or score > current["score"]:
                    chapter_scores[chapter_id] = {
                        "score": score,
                        "subject_id": payload.get("subject_id"),
                    }

            candidates = []
            for index, (chapter_id, data) in enumerate(
                sorted(chapter_scores.items(), key=lambda item: -item[1]["score"])
            ):
                score = data["score"]
                if score < VECTOR_MATCH_THRESHOLD:
                    continue
                candidates.append(
                    {
                        "chapter_id": chapter_id,
                        "subject_id": data.get("subject_id"),
                        "relevance": score,
                        "source": "vector_search",
                        "is_primary": index == 0,
                    }
                )
            return candidates[:3]

        def search_with_filter(query_filter: Filter) -> List[Dict[str, Any]]:
            results: List[Dict[str, Any]] = []
            for query_vector in query_vectors:
                results.extend(
                    qdrant_manager.search(
                        collection_name=qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
                        query_vector=query_vector,
                        query_filter=query_filter,
                        limit=10,
                    )
                )
            return results

        try:
            entity_subject_id = getattr(entity, "subject_id", None)
            if entity_subject_id:
                subject_candidates = aggregate(
                    search_with_filter(build_filter(entity_subject_id))
                )
                all_candidates = aggregate(search_with_filter(build_filter()))
                if not subject_candidates:
                    return all_candidates
                if (
                    all_candidates
                    and all_candidates[0]["chapter_id"]
                    != subject_candidates[0]["chapter_id"]
                    and all_candidates[0]["relevance"]
                    >= subject_candidates[0]["relevance"] + SUBJECT_FALLBACK_MARGIN
                ):
                    return all_candidates
                return subject_candidates

            return aggregate(search_with_filter(build_filter()))
        except Exception as exc:
            logger.error("Qdrant 检索失败", error=str(exc))
            return []
