"""Catalog chapter mapping module compatibility tests."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.catalog.canonical_chapter_service import CanonicalChapterService
from app.modules.catalog.chapter_mapping_service import ChapterMappingService
from app.services.chapter_mapping_service import (
    CanonicalChapterService as LegacyCanonicalChapterService,
)
from app.services.chapter_mapping_service import (
    ChapterMappingService as LegacyChapterMappingService,
)


def test_legacy_chapter_mapping_service_exports_catalog_implementations():
    assert LegacyCanonicalChapterService is CanonicalChapterService
    assert LegacyChapterMappingService is ChapterMappingService


@pytest.mark.asyncio
async def test_canonical_chapter_service_initializes_root_with_null_parent():
    existing_result = Mock()
    existing_result.scalar_one_or_none.return_value = None
    db = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(id="subject-1")),
        execute=AsyncMock(return_value=existing_result),
        add=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )

    result = await CanonicalChapterService(db).init_chapters(
        "subject-1",
        [{"name": "操作系统", "code": "OS"}],
    )

    assert result["created_count"] == 1
    assert result["chapter_ids"]["操作系统"]
    created_chapter = db.add.call_args.args[0]
    assert created_chapter.parent_id is None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_canonical_chapter_service_builds_parent_child_tree():
    created_at = datetime(2026, 7, 14, 12, 0, 0)
    root = SimpleNamespace(
        id="root",
        subject_id="subject-1",
        parent_id=None,
        level=1,
        name="操作系统",
        code="OS",
        aliases=[],
        description=None,
        sort_order=1,
        status="active",
        created_at=created_at,
    )
    child = SimpleNamespace(
        id="child",
        subject_id="subject-1",
        parent_id="root",
        level=2,
        name="进程管理",
        code="OS-1",
        aliases=["进程"],
        description=None,
        sort_order=2,
        status="active",
        created_at=created_at,
    )
    scalars = Mock()
    scalars.all.return_value = [root, child]
    query_result = Mock()
    query_result.scalars.return_value = scalars
    db = SimpleNamespace(execute=AsyncMock(return_value=query_result))

    chapters = await CanonicalChapterService(db).get_chapters("subject-1")

    assert [chapter["id"] for chapter in chapters] == ["root"]
    assert [chapter["id"] for chapter in chapters[0]["children"]] == ["child"]
    assert chapters[0]["created_at"] == "2026-07-14T12:00:00"
