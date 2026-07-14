"""Catalog chapter link persistence tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.mysql_models import QuestionChapterLink
from app.modules.catalog.chapter_link_store import ChapterLinkStore


def make_chapter(status: str = "active"):
    return SimpleNamespace(
        id="chapter-1",
        name="进程调度",
        outline_code="2.1",
        level=2,
        status=status,
    )


def make_query_result(existing_link=None):
    result = Mock()
    result.scalar_one_or_none.return_value = existing_link
    return result


@pytest.mark.asyncio
async def test_store_updates_existing_knowledge_point_link():
    existing_link = SimpleNamespace(
        relevance=0.4,
        source="manual",
        is_primary=False,
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=make_chapter()),
        execute=AsyncMock(
            return_value=make_query_result(existing_link)
        ),
        add=Mock(),
        commit=AsyncMock(),
    )

    response = await ChapterLinkStore(db).save_links(
        SimpleNamespace(id="kp-1"),
        "knowledge_point",
        [
            {
                "chapter_id": "chapter-1",
                "relevance": 0.92,
                "source": "vector_search",
                "is_primary": True,
            }
        ],
        "vector_search",
    )

    assert existing_link.relevance == 0.92
    assert existing_link.source == "vector_search"
    assert existing_link.is_primary is True
    db.add.assert_not_called()
    db.commit.assert_awaited_once()
    assert response == {
        "linked_count": 1,
        "primary_chapter": {
            "id": "chapter-1",
            "name": "进程调度",
            "outline_code": "2.1",
            "level": 2,
            "relevance": 0.92,
            "source": "vector_search",
        },
        "related_chapters": [],
        "strategy_used": "vector_search",
    }


@pytest.mark.asyncio
async def test_store_creates_new_question_link():
    db = SimpleNamespace(
        get=AsyncMock(return_value=make_chapter()),
        execute=AsyncMock(return_value=make_query_result()),
        add=Mock(),
        commit=AsyncMock(),
    )

    response = await ChapterLinkStore(db).save_links(
        SimpleNamespace(id="question-1"),
        "question",
        [
            {
                "chapter_id": "chapter-1",
                "relevance": 0.8,
                "source": "document_mapping",
                "is_primary": False,
            }
        ],
        "document_mapping",
    )

    created_link = db.add.call_args.args[0]
    assert isinstance(created_link, QuestionChapterLink)
    assert created_link.question_id == "question-1"
    assert created_link.canonical_chapter_id == "chapter-1"
    assert created_link.relevance == 0.8
    assert created_link.source == "document_mapping"
    assert created_link.is_primary is False
    assert created_link.created_by == "system"
    db.commit.assert_awaited_once()
    assert response["primary_chapter"] is None
    assert response["related_chapters"][0]["id"] == "chapter-1"


@pytest.mark.asyncio
async def test_store_skips_inactive_chapter_without_creating_link():
    db = SimpleNamespace(
        get=AsyncMock(return_value=make_chapter(status="inactive")),
        execute=AsyncMock(),
        add=Mock(),
        commit=AsyncMock(),
    )

    response = await ChapterLinkStore(db).save_links(
        SimpleNamespace(id="kp-1"),
        "knowledge_point",
        [
            {
                "chapter_id": "chapter-1",
                "relevance": 0.9,
                "source": "existing",
                "is_primary": True,
            }
        ],
        "existing",
    )

    db.execute.assert_not_awaited()
    db.add.assert_not_called()
    db.commit.assert_awaited_once()
    assert response == {
        "linked_count": 1,
        "primary_chapter": None,
        "related_chapters": [],
        "strategy_used": "existing",
    }
