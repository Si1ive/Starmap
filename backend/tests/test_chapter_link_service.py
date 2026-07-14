"""Catalog chapter link module tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.catalog.chapter_matcher import ChapterMatcher
from app.modules.catalog.chapter_link_service import ChapterLinkService


@pytest.mark.asyncio
async def test_chapter_matcher_returns_exact_name_as_high_confidence_hit():
    chapter = SimpleNamespace(
        id="chapter-1",
        subject_id="subject-1",
        name="进程调度",
        aliases=[],
        keywords=["调度算法"],
    )
    scalars = Mock()
    scalars.all.return_value = [chapter]
    result = Mock()
    result.scalars.return_value = scalars
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    match = await ChapterMatcher(db).match_by_keyword(
        title="进程调度",
        content="",
        subject_id="subject-1",
        topic_terms=[],
    )

    assert match == {
        "chapter_id": "chapter-1",
        "subject_id": "subject-1",
        "confidence": 1.0,
        "source": "keyword_match",
    }


@pytest.mark.asyncio
async def test_chapter_link_service_preserves_matcher_delegate_methods():
    service = ChapterLinkService(SimpleNamespace())
    expected = {
        "chapter_id": "chapter-1",
        "subject_id": "subject-1",
        "confidence": 0.9,
        "source": "keyword_match",
    }
    service.matcher.match_by_keyword = AsyncMock(return_value=expected)

    result = await service._match_by_keyword(
        title="调度算法",
        content="",
        subject_id="subject-1",
        topic_terms=[],
    )

    assert result == expected
    service.matcher.match_by_keyword.assert_awaited_once_with(
        title="调度算法",
        content="",
        subject_id="subject-1",
        topic_terms=[],
        include_content=True,
    )


@pytest.mark.asyncio
async def test_chapter_link_service_delegates_matched_results_to_store():
    chapter = SimpleNamespace(id="chapter-1", status="active")
    db = SimpleNamespace(get=AsyncMock(return_value=chapter))
    service = ChapterLinkService(db)
    expected = {
        "linked_count": 1,
        "primary_chapter": {"id": "chapter-1"},
        "related_chapters": [],
        "strategy_used": "existing",
    }
    service.link_store.save_links = AsyncMock(return_value=expected)
    entity = SimpleNamespace(
        id="question-1",
        primary_chapter_id="chapter-1",
        source_document_id=None,
    )

    result = await service._link_entity_to_chapters(entity, "question")

    assert result == expected
    service.link_store.save_links.assert_awaited_once_with(
        entity,
        "question",
        [
            {
                "chapter_id": "chapter-1",
                "relevance": 1.0,
                "source": "existing",
                "is_primary": True,
            }
        ],
        "existing",
    )


@pytest.mark.asyncio
async def test_chapter_link_service_uses_document_mapping_before_vector_search():
    service = ChapterLinkService(SimpleNamespace())
    mapping = {
        "chapter_id": "chapter-1",
        "relevance": 0.93,
        "source": "document_mapping",
        "is_primary": True,
        "mapping_type": "exact",
    }
    expected = {
        "linked_count": 1,
        "primary_chapter": {"id": "chapter-1"},
        "related_chapters": [],
        "strategy_used": "document_mapping",
    }
    service.document_resolver.resolve = AsyncMock(return_value=mapping)
    service._match_by_vector_search = AsyncMock()
    service.link_store.save_links = AsyncMock(return_value=expected)
    entity = SimpleNamespace(
        id="question-1",
        primary_chapter_id=None,
        source_document_id="document-1",
    )

    result = await service._link_entity_to_chapters(entity, "question")

    assert result == expected
    service.document_resolver.resolve.assert_awaited_once_with(
        entity,
        "question",
    )
    service._match_by_vector_search.assert_not_awaited()
    service.link_store.save_links.assert_awaited_once_with(
        entity,
        "question",
        [mapping],
        "document_mapping",
    )


@pytest.mark.asyncio
async def test_chapter_link_service_delegates_question_backfill():
    service = ChapterLinkService(SimpleNamespace())
    expected = {"scanned": 1, "updated": 1}
    service.question_backfill.backfill = AsyncMock(return_value=expected)

    result = await service.backfill_question_chapters(
        review_status="rejected",
        status="inactive",
        subject_id="subject-1",
        limit=20,
        force=True,
        dry_run=True,
    )

    assert result == expected
    service.question_backfill.backfill.assert_awaited_once_with(
        review_status="rejected",
        status="inactive",
        subject_id="subject-1",
        limit=20,
        force=True,
        dry_run=True,
    )
