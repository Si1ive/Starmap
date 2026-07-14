from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.catalog.chapter_diagnostics_service import (
    ChapterOwnershipDiagnosticsService,
)


def _scalar_result(items):
    scalars = Mock()
    scalars.all.return_value = items
    result = Mock()
    result.scalars.return_value = scalars
    return result


def _row_result(items):
    result = Mock()
    result.all.return_value = items
    return result


@pytest.mark.asyncio
async def test_diagnostics_service_assembles_page_block_and_entity_counts():
    document = SimpleNamespace(
        id="document-1",
        title="数据结构教材",
        doc_type="textbook",
        page_count=1,
    )
    block = SimpleNamespace(
        id="block-1",
        page_no=1,
        order_no=1,
        block_type="paragraph",
        content_text="1 下列关于队列的说法正确的是？",
        content_md=None,
    )
    section = SimpleNamespace(
        id="section-1",
        title="队列",
        section_path="数据结构 > 队列",
        level=2,
        page_start=1,
        page_end=1,
        block_start_id="block-1",
        block_end_id="block-1",
        confidence=0.95,
    )
    mapping = SimpleNamespace(
        id="mapping-1",
        mapping_type="exact",
        confidence=0.98,
        review_status="approved",
    )
    chapter = SimpleNamespace(
        id="chapter-1",
        name="队列",
        code="DS-QUEUE",
    )
    subject = SimpleNamespace(id="subject-1", name="数据结构")
    source_link = SimpleNamespace(
        entity_type="question",
        page_start=1,
        page_end=1,
        block_ids=["block-1"],
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=document),
        execute=AsyncMock(side_effect=[
            _scalar_result([block]),
            _scalar_result([block]),
            _scalar_result([section]),
            _row_result([(mapping, section, chapter, subject)]),
            _scalar_result([1]),
            _scalar_result([source_link]),
        ]),
    )

    result = await ChapterOwnershipDiagnosticsService(
        db
    ).get_chapter_ownership_diagnostics("document-1")

    assert result["document_id"] == "document-1"
    assert result["summary"]["pages_ok"] == 1
    assert result["summary"]["blocks_ok"] == 1
    assert result["summary"]["question_like_blocks"] == 1
    assert result["summary"]["extracted_question_count"] == 1
    assert result["pages"][0]["extraction_mapping"][
        "canonical_chapter_id"
    ] == "chapter-1"
    assert result["blocks"][0]["signals"]["looks_like_question_start"] is True
    assert result["blocks"][0]["extracted"]["question_count"] == 1
    assert result["sections"][0]["mapping"]["mapping_id"] == "mapping-1"
