from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.datastructures import UploadFile

from app.modules.catalog.outline_parse_service import (
    OUTLINE_PARSER_NAME,
    OutlineParseJob,
    OutlineParseRunExecutor,
    OutlineParseTaskService,
)


def _run():
    return SimpleNamespace(
        document_id=None,
        status="processing",
        current_stage="parsing",
        stage_detail=None,
        total_subjects=0,
        processed_subjects=0,
        successful_subjects=0,
        result_summary=None,
        error_detail=None,
        completed_at=None,
    )


def _upload(filename: str, content: bytes = b"pdf-content") -> UploadFile:
    return UploadFile(BytesIO(content), filename=filename)


@pytest.mark.asyncio
async def test_start_upload_creates_run_and_schedules_mineru_job(tmp_path):
    db = SimpleNamespace(
        add=Mock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    corpus_service = SimpleNamespace(
        register_single_file=AsyncMock(
            return_value={
                "corpus_file_id": "corpus-1",
                "is_new": True,
            }
        )
    )
    scheduled = []
    service = OutlineParseTaskService(
        db,
        upload_dir=tmp_path,
        corpus_service=corpus_service,
        schedule_job=scheduled.append,
    )

    result = await service.start(
        _upload("../2026大纲.pdf"),
        parser_name=None,
    )

    assert result["corpus_file_id"] == "corpus-1"
    assert result["file_name"] == "2026大纲.pdf"
    assert result["status"] == "processing"
    assert len(scheduled) == 1
    assert scheduled[0].file_name == "2026大纲.pdf"
    assert scheduled[0].is_new_file is True
    assert next(tmp_path.iterdir()).read_bytes() == b"pdf-content"
    created_run = db.add.call_args.args[0]
    assert created_run.outline_name == "2026大纲.pdf"
    assert created_run.current_stage == "parsing"


@pytest.mark.asyncio
async def test_start_upload_rejects_non_mineru_parser(tmp_path):
    db = SimpleNamespace(
        add=Mock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    service = OutlineParseTaskService(db, upload_dir=tmp_path)

    upload = _upload("outline.pdf")
    with pytest.raises(ValueError, match="固定使用 MinerU"):
        await service.start(
            upload,
            parser_name="other",
        )

    assert list(tmp_path.iterdir()) == []
    assert upload.file.closed
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_start_upload_only_accepts_pdf(tmp_path):
    db = SimpleNamespace(
        add=Mock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    service = OutlineParseTaskService(db, upload_dir=tmp_path)
    upload = _upload("outline.docx")

    with pytest.raises(ValueError, match="仅支持 pdf"):
        await service.start(upload, parser_name=None)

    assert upload.file.closed
    assert list(tmp_path.iterdir()) == []
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_start_upload_removes_duplicate_temporary_file(tmp_path):
    db = SimpleNamespace(
        add=Mock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    corpus_service = SimpleNamespace(
        register_single_file=AsyncMock(
            return_value={
                "corpus_file_id": "corpus-existing",
                "is_new": False,
            }
        )
    )
    scheduled = []
    service = OutlineParseTaskService(
        db,
        upload_dir=tmp_path,
        corpus_service=corpus_service,
        schedule_job=scheduled.append,
    )

    await service.start(
        _upload("outline.pdf"),
        parser_name=OUTLINE_PARSER_NAME,
    )

    assert list(tmp_path.iterdir()) == []
    assert scheduled[0].corpus_file_id == "corpus-existing"
    assert scheduled[0].is_new_file is False


@pytest.mark.asyncio
async def test_executor_parses_new_file_with_mineru_and_completes():
    run = _run()
    db = SimpleNamespace(
        get=AsyncMock(return_value=run),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    parse_service = SimpleNamespace(
        parse_document=AsyncMock(
            return_value={"document_id": "document-1"}
        )
    )
    llm_service = SimpleNamespace(
        split_outline_with_progress=AsyncMock(
            return_value={
                "document_id": "document-1",
                "subjects": [
                    {"subject_name": "数据结构"},
                    {"subject_name": "操作系统", "error": "timeout"},
                ],
            }
        )
    )
    executor = OutlineParseRunExecutor(
        db,
        parse_service=parse_service,
        llm_service=llm_service,
    )

    await executor.execute(
        OutlineParseJob(
            run_id="run-1",
            corpus_file_id="corpus-1",
            is_new_file=True,
            file_name="outline.pdf",
        )
    )

    parse_service.parse_document.assert_awaited_once_with(
        "corpus-1",
        parser_name="mineru",
        parse_mode="primary",
    )
    assert run.document_id == "document-1"
    assert run.status == "partial"
    assert run.current_stage == "completed"
    assert run.total_subjects == 2
    assert run.successful_subjects == 1
    assert run.error_detail == "操作系统：timeout"
    assert run.result_summary["file_name"] == "outline.pdf"
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_executor_reuses_existing_document_with_blocks():
    run = _run()
    document = SimpleNamespace(id="document-existing")
    db = SimpleNamespace(
        get=AsyncMock(return_value=run),
        scalar=AsyncMock(side_effect=[document, 8]),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    parse_service = SimpleNamespace(parse_document=AsyncMock())
    llm_service = SimpleNamespace(
        split_outline_with_progress=AsyncMock(
            return_value={
                "document_id": "document-existing",
                "subjects": [],
            }
        )
    )
    executor = OutlineParseRunExecutor(
        db,
        parse_service=parse_service,
        llm_service=llm_service,
    )

    await executor.execute(
        OutlineParseJob(
            run_id="run-1",
            corpus_file_id="corpus-existing",
            is_new_file=False,
            file_name="outline.pdf",
        )
    )

    parse_service.parse_document.assert_not_awaited()
    llm_service.split_outline_with_progress.assert_awaited_once_with(
        "run-1",
        "document-existing",
    )
    assert run.document_id == "document-existing"


@pytest.mark.asyncio
async def test_executor_retries_incomplete_existing_document():
    run = _run()
    document = SimpleNamespace(id="document-incomplete")
    db = SimpleNamespace(
        get=AsyncMock(return_value=run),
        scalar=AsyncMock(side_effect=[document, 0]),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    parse_service = SimpleNamespace(
        parse_document=AsyncMock(
            return_value={"document_id": "document-reparsed"}
        )
    )
    llm_service = SimpleNamespace(
        split_outline_with_progress=AsyncMock(
            return_value={
                "document_id": "document-reparsed",
                "subjects": [{"subject_name": "数据结构"}],
            }
        )
    )
    executor = OutlineParseRunExecutor(
        db,
        parse_service=parse_service,
        llm_service=llm_service,
    )

    await executor.execute(
        OutlineParseJob(
            run_id="run-1",
            corpus_file_id="corpus-existing",
            is_new_file=False,
            file_name="outline.pdf",
        )
    )

    parse_service.parse_document.assert_awaited_once_with(
        "corpus-existing",
        parser_name="mineru",
        parse_mode="retry",
    )
    assert run.document_id == "document-reparsed"
    assert run.status == "done"


@pytest.mark.asyncio
async def test_executor_rolls_back_before_persisting_failure():
    run = _run()
    db = SimpleNamespace(
        get=AsyncMock(side_effect=[run, run]),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    parse_service = SimpleNamespace(
        parse_document=AsyncMock(side_effect=RuntimeError("MinerU failed"))
    )
    llm_service = SimpleNamespace(
        split_outline_with_progress=AsyncMock()
    )
    executor = OutlineParseRunExecutor(
        db,
        parse_service=parse_service,
        llm_service=llm_service,
    )

    await executor.execute(
        OutlineParseJob(
            run_id="run-1",
            corpus_file_id="corpus-1",
            is_new_file=True,
            file_name="outline.pdf",
        )
    )

    db.rollback.assert_awaited_once()
    assert run.status == "failed"
    assert run.current_stage == "failed"
    assert run.error_detail == "MinerU failed"
    assert run.completed_at is not None
    llm_service.split_outline_with_progress.assert_not_awaited()


@pytest.mark.asyncio
async def test_executor_marks_all_subject_failures_as_failed():
    run = _run()
    db = SimpleNamespace(
        get=AsyncMock(return_value=run),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    parse_service = SimpleNamespace(
        parse_document=AsyncMock(
            return_value={"document_id": "document-1"}
        )
    )
    llm_service = SimpleNamespace(
        split_outline_with_progress=AsyncMock(
            return_value={
                "document_id": "document-1",
                "subjects": [
                    {"subject_name": "数据结构", "error": "timeout"},
                    {"subject_name": "操作系统", "error": "invalid json"},
                ],
            }
        )
    )
    executor = OutlineParseRunExecutor(
        db,
        parse_service=parse_service,
        llm_service=llm_service,
    )

    await executor.execute(
        OutlineParseJob(
            run_id="run-1",
            corpus_file_id="corpus-1",
            is_new_file=True,
            file_name="outline.pdf",
        )
    )

    assert run.status == "failed"
    assert run.current_stage == "failed"
    assert run.successful_subjects == 0
    assert "数据结构：timeout" in run.error_detail
    assert "操作系统：invalid json" in run.error_detail
    assert run.result_summary["subjects"][0]["error"] == "timeout"
