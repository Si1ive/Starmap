import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.document_parse_service import DocumentParseService, _normalize_asset_type_for_db
from app.services.document_parsers import ParsedDocumentResult, ParsedPage, ParsedBlock, ParsedAsset


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_parse_document_rejects_when_already_parsing():
    db = AsyncMock()
    corpus_file = SimpleNamespace(id="file_1", local_path="/tmp/demo.pdf", status="parsing")
    db.execute = AsyncMock(return_value=_ScalarResult(corpus_file))

    service = DocumentParseService(db)

    with pytest.raises(ValueError, match="正在解析中"):
        await service.parse_document("file_1")


@pytest.mark.asyncio
async def test_parse_document_rejects_duplicate_primary_parse():
    db = AsyncMock()
    corpus_file = SimpleNamespace(id="file_1", local_path="/tmp/demo.pdf", status="parsed")
    document = SimpleNamespace(id="doc_1")
    db.execute = AsyncMock(side_effect=[_ScalarResult(corpus_file), _ScalarResult(document)])

    service = DocumentParseService(db)

    with patch("app.services.document_parse_service.Path.exists", return_value=True):
        with pytest.raises(ValueError, match="已成功解析"):
            await service.parse_document("file_1", parse_mode="primary")


def test_serialize_parse_result_contains_structured_payload():
    service = DocumentParseService(AsyncMock())
    result = ParsedDocumentResult(
        parser_name="docling",
        parser_version="2.x",
        pages=[ParsedPage(page_no=1, width=100, height=200)],
        blocks=[ParsedBlock(page_no=1, block_type="title", order_no=0, content_text="第1章")],
        assets=[ParsedAsset(page_no=1, asset_type="figure", caption_text="图1")],
        document_markdown="# 第1章",
        confidence=0.98,
        metadata={"source_file": "/tmp/demo.pdf"},
    )

    payload = service._serialize_parse_result(result)

    assert payload["parser_name"] == "docling"
    assert payload["page_count"] == 1
    assert payload["block_count"] == 1
    assert payload["asset_count"] == 1
    assert payload["pages"][0]["page_no"] == 1
    assert payload["blocks"][0]["content_text"] == "第1章"
    assert payload["assets"][0]["caption_text"] == "图1"


def test_normalize_asset_type_maps_unknown_to_other():
    assert _normalize_asset_type_for_db("code") == "other"
    assert _normalize_asset_type_for_db("table") == "table"
