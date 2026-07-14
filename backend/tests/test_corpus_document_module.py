from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.mysql_models import CorpusFile, Document
from app.modules.corpus.document_service import CorpusDocumentService
from app.modules.corpus.extraction_tasks import EntityExtractionTaskService
from app.services.document_parse_service import DocumentParseService


def test_extract_raw_page_data_supports_mineru_page_indexes():
    raw_data, parser_name = CorpusDocumentService.extract_raw_page_data(
        {
            "parser": "mineru",
            "content_list": [
                {"page_idx": 0, "text": "page one"},
                {"page_idx": "1", "text": "page two"},
                {"page_idx": "invalid", "text": "ignored"},
            ],
        },
        2,
    )

    assert parser_name == "mineru"
    assert raw_data == {
        "parser": "mineru",
        "content_list": [{"page_idx": "1", "text": "page two"}],
    }


def test_extract_raw_page_data_supports_legacy_payload():
    raw_data, parser_name = CorpusDocumentService.extract_raw_page_data(
        {
            "parser_name": "legacy",
            "blocks": [
                {"page_no": "2", "text": "target"},
                {"page_no": 3, "text": "other"},
            ],
            "assets": [
                {"page_no": 2, "file_path": "target.png"},
                {"page_no": 3, "file_path": "other.png"},
            ],
        },
        2,
    )

    assert parser_name == "legacy"
    assert raw_data == {
        "parser": "legacy",
        "blocks": [{"page_no": "2", "text": "target"}],
        "assets": [{"page_no": 2, "file_path": "target.png"}],
    }


@pytest.mark.asyncio
async def test_page_analysis_renders_pdf_off_event_loop(monkeypatch, tmp_path):
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF")
    document = {
        "corpus_file_id": "file-1",
        "pages": [{"page_no": 2, "width": 100}],
        "blocks": [{"page_no": 2, "content_text": "block"}],
        "assets": [{"page_no": 2, "file_path": "asset.png"}],
        "raw_parser_output": {
            "parser": "mineru",
            "content_list": [{"page_idx": 1, "text": "raw"}],
        },
    }

    async def get_document_detail(_service, document_id):
        assert document_id == "doc-1"
        return document

    monkeypatch.setattr(
        DocumentParseService,
        "get_document_detail",
        get_document_detail,
    )
    to_thread = AsyncMock(return_value="encoded-page")
    monkeypatch.setattr(
        "app.modules.corpus.document_service.asyncio.to_thread",
        to_thread,
    )

    db = AsyncMock()
    db.get.return_value = SimpleNamespace(local_path=str(source_path))
    result = await CorpusDocumentService(db).get_page_analysis(
        "doc-1",
        page_no=2,
    )

    db.get.assert_awaited_once_with(CorpusFile, "file-1")
    to_thread.assert_awaited_once()
    assert result["page_image"] == "data:image/png;base64,encoded-page"
    assert result["blocks"] == document["blocks"]
    assert result["raw_parse_data"]["content_list"] == [
        {"page_idx": 1, "text": "raw"}
    ]


@pytest.mark.asyncio
async def test_extraction_task_persists_before_dispatch(monkeypatch):
    events = []
    db = AsyncMock()
    db.add = Mock()
    db.get.return_value = SimpleNamespace(id="doc-1")
    query_result = Mock()
    query_result.scalar_one_or_none.return_value = None
    db.execute.return_value = query_result

    async def commit():
        events.append("commit")

    db.commit.side_effect = commit
    service = EntityExtractionTaskService(db)
    dispatch = Mock(side_effect=lambda _run_id: events.append("dispatch"))
    monkeypatch.setattr(service, "_schedule", dispatch)

    run, created = await service.start(
        "doc-1",
        extract_knowledge=True,
        extract_questions=False,
        subject_id="subject-1",
    )

    db.get.assert_awaited_once_with(
        Document,
        "doc-1",
        with_for_update=True,
    )
    assert db.add.call_args.args[0] is run
    assert events == ["commit", "dispatch"]
    assert created is True
    assert run.status == "running"
    assert run.extract_knowledge is True
    assert run.extract_questions is False
    assert run.subject_id == "subject-1"


@pytest.mark.asyncio
async def test_extraction_task_reuses_running_run(monkeypatch):
    running_run = SimpleNamespace(id="run-existing", status="running")
    db = AsyncMock()
    db.add = Mock()
    db.get.return_value = SimpleNamespace(id="doc-1")
    query_result = Mock()
    query_result.scalar_one_or_none.return_value = running_run
    db.execute.return_value = query_result
    service = EntityExtractionTaskService(db)
    dispatch = Mock()
    monkeypatch.setattr(service, "_schedule", dispatch)

    run, created = await service.start(
        "doc-1",
        extract_knowledge=True,
        extract_questions=True,
        subject_id=None,
    )

    assert run is running_run
    assert created is False
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    dispatch.assert_not_called()
