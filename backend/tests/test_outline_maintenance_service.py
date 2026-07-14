from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.catalog.outline_maintenance_service import (
    OutlineMaintenanceService,
)


@pytest.mark.asyncio
async def test_delete_outline_reports_missing_without_writes():
    db = SimpleNamespace(
        get=AsyncMock(return_value=None),
        scalar=AsyncMock(),
        execute=AsyncMock(),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )

    result = await OutlineMaintenanceService(db).delete_outline("missing")

    assert result is None
    db.scalar.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_outline_clears_children_before_outline():
    outline = SimpleNamespace(id="outline-1", name="2026 年 408 大纲")
    db = SimpleNamespace(
        get=AsyncMock(return_value=outline),
        scalar=AsyncMock(return_value=18),
        execute=AsyncMock(),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )

    result = await OutlineMaintenanceService(db).delete_outline("outline-1")

    assert result == {
        "outline_id": "outline-1",
        "outline_name": "2026 年 408 大纲",
        "deleted_chapters": 18,
        "message": "大纲已删除",
    }
    statements = [
        str(call.args[0]).lower()
        for call in db.execute.await_args_list
    ]
    assert len(statements) == 2
    assert "delete from canonical_chapters" in statements[0]
    assert "canonical_chapters.outline_id" in statements[0]
    assert "delete from exam_outline_subjects" in statements[1]
    assert "exam_outline_subjects.outline_id" in statements[1]
    db.delete.assert_awaited_once_with(outline)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_outline_normalizes_empty_chapter_count():
    outline = SimpleNamespace(id="outline-1", name="空大纲")
    db = SimpleNamespace(
        get=AsyncMock(return_value=outline),
        scalar=AsyncMock(return_value=None),
        execute=AsyncMock(),
        delete=AsyncMock(),
        commit=AsyncMock(),
    )

    result = await OutlineMaintenanceService(db).delete_outline("outline-1")

    assert result["deleted_chapters"] == 0
