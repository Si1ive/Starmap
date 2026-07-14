"""Catalog chapter link module compatibility tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.catalog.chapter_matcher import ChapterMatcher
from app.modules.catalog.chapter_link_service import ChapterLinkService
from app.services.chapter_link_service import ChapterLinkService as LegacyChapterLinkService


def test_legacy_chapter_link_service_exports_catalog_implementation():
    assert LegacyChapterLinkService is ChapterLinkService


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
