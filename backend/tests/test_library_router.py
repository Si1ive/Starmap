from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException, UploadFile

from app.modules.library.router import (
    UpdateSourceRetrievalRequest,
    delete_library_source,
    update_source_retrieval,
    upload_library_sources,
)


@pytest.mark.asyncio
async def test_user_library_rejects_renamed_non_pdf_before_persistence():
    upload = UploadFile(file=BytesIO(b"plain text"), filename="fake.pdf")

    with pytest.raises(HTTPException) as error:
        await upload_library_sources(
            files=[upload],
            current=SimpleNamespace(user=SimpleNamespace(id=UUID(int=1))),
            db=AsyncMock(),
        )

    assert error.value.status_code == 400
    assert error.value.detail == "文件内容不是有效的 PDF"


@pytest.mark.asyncio
async def test_user_library_upload_binds_owner_and_starts_full_ingestion(monkeypatch):
    owner_id = UUID("01900000-0000-7000-8000-000000000001")
    upload_result = {
        "success_items": [{"corpus_file_id": "file-1", "status": "success"}],
        "skipped_items": [],
        "failed_items": [],
    }
    upload_files = AsyncMock(return_value=upload_result)
    start_parse = AsyncMock(return_value={"run_id": "run-1", "status": "running"})
    monkeypatch.setattr(
        "app.modules.library.router.CorpusApplicationService.upload_files",
        upload_files,
    )
    monkeypatch.setattr(
        "app.modules.library.router.CorpusApplicationService.start_parse",
        start_parse,
    )

    response = await upload_library_sources(
        files=[UploadFile(file=BytesIO(b"%PDF-1.7\n"), filename="paper.pdf")],
        current=SimpleNamespace(user=SimpleNamespace(id=owner_id)),
        db=AsyncMock(),
    )

    upload_files.assert_awaited_once()
    assert upload_files.await_args.kwargs["owner_user_id"] == owner_id
    start_parse.assert_awaited_once_with(
        "file-1",
        parser_name=None,
        parse_mode="primary",
        auto_extract=True,
    )
    assert response.data["parse_runs"] == [
        {"run_id": "run-1", "status": "running"},
    ]


@pytest.mark.asyncio
async def test_personal_source_can_leave_retrieval_without_being_deleted():
    source = SimpleNamespace(id="source-1", retrieval_enabled=True)
    db = AsyncMock()
    db.scalar.return_value = source

    response = await update_source_retrieval(
        source_id=source.id,
        payload=UpdateSourceRetrievalRequest(enabled=False),
        current=SimpleNamespace(user=SimpleNamespace(id=UUID(int=1))),
        db=db,
    )

    assert source.retrieval_enabled is False
    assert response.data == {"id": source.id, "retrieval_enabled": False}
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_personal_source_delete_immediately_disables_retrieval():
    source = SimpleNamespace(
        id="source-1",
        retrieval_enabled=True,
        deleted_at=None,
        status="indexed",
    )
    db = AsyncMock()
    db.scalar.return_value = source

    response = await delete_library_source(
        source_id=source.id,
        current=SimpleNamespace(user=SimpleNamespace(id=UUID(int=1))),
        db=db,
    )

    assert source.retrieval_enabled is False
    assert source.deleted_at is not None
    assert source.status == "archived"
    assert response.data == {"id": source.id, "deletion_status": "completed"}
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_personal_source_mutation_uses_same_404_for_unowned_or_deleted_source():
    db = AsyncMock()
    db.scalar.return_value = None

    with pytest.raises(HTTPException) as error:
        await update_source_retrieval(
            source_id="another-users-source",
            payload=UpdateSourceRetrievalRequest(enabled=False),
            current=SimpleNamespace(user=SimpleNamespace(id=UUID(int=1))),
            db=db,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "个人资料不存在"
