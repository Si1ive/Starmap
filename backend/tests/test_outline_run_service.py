from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.catalog.outline_run_service import (
    OutlineRunService,
    serialize_outline_run,
)


def _run(**overrides):
    values = {
        "id": "run-1",
        "document_id": "document-1",
        "outline_id": "outline-1",
        "outline_name": "2026 年大纲",
        "year": 2026,
        "version": "v1.0",
        "status": "processing",
        "current_stage": "splitting",
        "stage_detail": "正在拆分",
        "total_subjects": 4,
        "processed_subjects": 3,
        "successful_subjects": 2,
        "current_subject_name": "操作系统",
        "created_chapters": 10,
        "updated_chapters": 2,
        "error_detail": None,
        "result_summary": {"file_name": "408.pdf", "subjects": []},
        "started_at": datetime(2026, 7, 14, 10, 0, 0),
        "completed_at": None,
        "created_at": datetime(2026, 7, 14, 9, 59, 0),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _multiple_result(items):
    return SimpleNamespace(
        scalars=Mock(
            return_value=SimpleNamespace(
                all=Mock(return_value=items),
            )
        )
    )


def test_serialize_outline_run_preserves_detail_contract():
    data = serialize_outline_run(
        _run(),
        include_result_summary=True,
    )

    assert data["progress"] == 75.0
    assert data["result_summary"]["file_name"] == "408.pdf"
    assert "file_name" not in data
    assert data["started_at"] == "2026-07-14T10:00:00"
    assert data["completed_at"] is None


def test_serialize_outline_run_preserves_list_contract():
    data = serialize_outline_run(
        _run(total_subjects=0, processed_subjects=0),
        include_result_summary=False,
    )

    assert data["progress"] == 0
    assert data["file_name"] == "408.pdf"
    assert "result_summary" not in data


@pytest.mark.asyncio
async def test_list_runs_serializes_query_results():
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=_multiple_result(
                [_run(status="done", processed_subjects=4)]
            )
        )
    )

    result = await OutlineRunService(db).list_runs(
        document_id="document-1",
        status="done",
        limit=20,
    )

    assert result["items"][0]["status"] == "done"
    assert result["items"][0]["progress"] == 100.0
    assert result["items"][0]["file_name"] == "408.pdf"


@pytest.mark.asyncio
async def test_delete_run_reports_missing_without_commit():
    db = SimpleNamespace(
        get=AsyncMock(return_value=None),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )

    deleted = await OutlineRunService(db).delete_run("missing")

    assert deleted is False
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_delete_counts_unique_requests_and_existing_rows():
    runs = [_run(id="run-1"), _run(id="run-2")]
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_multiple_result(runs)),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )

    result = await OutlineRunService(db).batch_delete(
        ["run-1", "run-1", "run-2", "missing"]
    )

    assert result == {
        "deleted_count": 2,
        "requested_count": 3,
    }
    assert db.delete.await_count == 2
    db.commit.assert_awaited_once()
