"""Build RAG context and traceable citations from retrieval results."""

from typing import Any, Dict, List, Tuple

from app.models.transaction import SourceItem


def build_retrieval_context(
    retrieval_result: Dict[str, Any],
) -> Tuple[List[str], List[SourceItem]]:
    """Convert retrieval output into prompt context and deduplicated citations."""
    context_parts: List[str] = []
    sources: List[SourceItem] = []

    outline_expansion = retrieval_result.get("outline_expansion") or {}
    matched_chapters = outline_expansion.get("matched_chapters") or []
    if matched_chapters:
        chapter_names = [
            chapter.get("name", "")
            for chapter in matched_chapters[:3]
            if isinstance(chapter, dict)
        ]
        context_parts.append(
            f"[大纲定位] 用户问题涉及考点: {', '.join(chapter_names)}"
        )

    seen_sources = set()
    for index, item in enumerate(retrieval_result.get("results") or [], 1):
        if not isinstance(item, dict):
            continue

        source = item.get("source") or {}
        content = item.get("context_text") or item.get("content_text", "")
        if content:
            source_info = ""
            if source.get("filename"):
                source_info = f" [来源: {source['filename']}"
                if source.get("page_no"):
                    source_info += f" 第{source['page_no']}页"
                source_info += "]"
            context_parts.append(f"[{index}]{source_info}\n{content}")

        entity_type = item.get("entity_type")
        entity_id = item.get("entity_id")
        document_id = source.get("document_id")
        source_key = (entity_type, entity_id, document_id)
        if source_key in seen_sources or not any(source_key):
            continue
        seen_sources.add(source_key)

        source_url = _build_source_url(entity_type, entity_id)
        source_title = source.get("filename") or {
            "knowledge_point": "知识点",
            "question": "题目",
        }.get(entity_type, "知识库内容")
        sources.append(SourceItem(
            type=entity_type or "document",
            title=source_title,
            content=(item.get("content_text") or "")[:240] or None,
            url=source_url,
            entity_id=entity_id,
            document_id=document_id,
            page_no=source.get("page_no"),
            score=item.get("score"),
        ))

    return context_parts, sources


def _build_source_url(
    entity_type: Any,
    entity_id: Any,
) -> str | None:
    if entity_type == "knowledge_point" and entity_id:
        return f"/knowledge/{entity_id}"
    if entity_type == "question" and entity_id:
        return f"/practice?question_id={entity_id}"
    return None
