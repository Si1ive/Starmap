from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import UploadFile

from app.modules.corpus.file_service import (
    BACKEND_ROOT,
    CorpusFileService,
    _resolve_download_path,
)
from app.modules.corpus.service import CorpusApplicationService


@pytest.mark.asyncio
async def test_start_parse_persists_running_state_before_dispatch(monkeypatch):
    corpus_file = SimpleNamespace(
        id="file-1",
        status="pending",
        error_detail="old failure",
    )
    parser = SimpleNamespace(name="mineru", version="2.5")
    db = AsyncMock()
    db.add = Mock()
    db.get.return_value = corpus_file

    monkeypatch.setattr(
        "app.modules.corpus.service.DocumentParseService._get_parser",
        AsyncMock(return_value=parser),
    )
    dispatch = Mock()
    service = CorpusApplicationService(db)
    monkeypatch.setattr(service, "_schedule_parse", dispatch)

    result = await service.start_parse(
        "file-1",
        parser_name="mineru",
        parse_mode="retry",
    )

    parse_run = db.add.call_args.args[0]
    assert parse_run.corpus_file_id == "file-1"
    assert parse_run.parser_name == "mineru"
    assert parse_run.parse_mode == "retry"
    assert parse_run.status == "running"
    assert corpus_file.status == "parsing"
    assert corpus_file.error_detail is None
    db.commit.assert_awaited_once()
    dispatch.assert_called_once_with(
        parse_run.id,
        "file-1",
        "mineru",
        "retry",
    )
    assert result == {
        "run_id": parse_run.id,
        "status": "running",
        "corpus_file_id": "file-1",
    }


@pytest.mark.asyncio
async def test_upload_sanitizes_name_and_removes_duplicate_copy(monkeypatch, tmp_path):
    captured = {}

    async def register_single_file(
        _service,
        file_path,
        batch_label=None,
        file_name=None,
    ):
        captured.update(
            file_path=file_path,
            batch_label=batch_label,
            file_name=file_name,
        )
        return {
            "corpus_file_id": "existing-file",
            "status": "parsed",
            "is_new": False,
        }

    monkeypatch.setattr(
        CorpusFileService,
        "register_single_file",
        register_single_file,
    )
    upload = UploadFile(
        file=BytesIO(b"pdf"),
        filename="../../unsafe.pdf",
    )
    service = CorpusApplicationService(
        AsyncMock(),
        upload_dir=tmp_path,
        max_upload_bytes=1024,
    )

    result = await service.upload_files([upload], batch_label="batch-1")

    assert captured["file_name"] == "unsafe.pdf"
    assert captured["batch_label"] == "batch-1"
    assert tmp_path in Path(captured["file_path"]).parents
    assert list(tmp_path.iterdir()) == []
    assert result["success_count"] == 0
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file_without_leaving_copy(tmp_path):
    upload = UploadFile(
        file=BytesIO(b"too-large"),
        filename="large.pdf",
    )
    service = CorpusApplicationService(
        AsyncMock(),
        upload_dir=tmp_path,
        max_upload_bytes=4,
    )

    result = await service.upload_files([upload], batch_label="batch-1")

    assert result["failed_count"] == 1
    assert "文件大小超过限制" in result["failed_items"][0]["error"]
    assert list(tmp_path.iterdir()) == []


def test_container_download_path_resolves_from_backend_root(
    monkeypatch,
    tmp_path,
):
    local_downloads = tmp_path / "downloads"
    local_downloads.mkdir()
    target = local_downloads / "paper.pdf"
    target.write_bytes(b"pdf")

    monkeypatch.setattr(
        "app.modules.corpus.file_service._LOCAL_DOWNLOADS",
        str(local_downloads),
    )

    assert BACKEND_ROOT.name == "backend"
    assert _resolve_download_path("/app/downloads/paper.pdf") == target
