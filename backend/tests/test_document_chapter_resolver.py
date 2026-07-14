"""Document section chapter resolver tests."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.catalog.document_chapter_resolver import (
    DocumentSectionChapterResolver,
)


def make_scalar_result(value):
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_document_resolver_returns_approved_section_mapping():
    source_link = SimpleNamespace(block_ids=["block-1"])
    block = SimpleNamespace(page_no=12)
    section = SimpleNamespace(id="section-1")
    mapping = SimpleNamespace(
        canonical_chapter_id="chapter-1",
        confidence=Decimal("0.9300"),
        mapping_type="exact",
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                make_scalar_result(source_link),
                make_scalar_result(section),
                make_scalar_result(mapping),
            ]
        ),
        get=AsyncMock(return_value=block),
    )

    result = await DocumentSectionChapterResolver(db).resolve(
        SimpleNamespace(id="question-1", source_document_id="document-1"),
        "question",
    )

    assert result == {
        "chapter_id": "chapter-1",
        "relevance": 0.93,
        "source": "document_mapping",
        "is_primary": True,
        "mapping_type": "exact",
    }
    assert db.execute.await_count == 3
    db.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_document_resolver_returns_none_without_source_link():
    db = SimpleNamespace(
        execute=AsyncMock(return_value=make_scalar_result(None)),
        get=AsyncMock(),
    )

    result = await DocumentSectionChapterResolver(db).resolve(
        SimpleNamespace(id="kp-1", source_document_id="document-1"),
        "knowledge_point",
    )

    assert result is None
    db.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_resolver_returns_none_when_source_block_was_removed():
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=make_scalar_result(
                SimpleNamespace(block_ids=["missing-block"])
            )
        ),
        get=AsyncMock(return_value=None),
    )

    result = await DocumentSectionChapterResolver(db).resolve(
        SimpleNamespace(id="question-1", source_document_id="document-1"),
        "question",
    )

    assert result is None
    assert db.execute.await_count == 1
    db.get.assert_awaited_once()
