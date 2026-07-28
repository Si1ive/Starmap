from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException, UploadFile

from app.modules.library.router import upload_library_sources


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
