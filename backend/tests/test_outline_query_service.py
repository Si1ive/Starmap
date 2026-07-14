from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.catalog.outline_query_service import (
    get_outline_chapters,
    get_outline_subjects,
    list_outlines,
)


def _scalars_result(items):
    return SimpleNamespace(
        scalars=Mock(
            return_value=SimpleNamespace(
                all=Mock(return_value=items),
            )
        )
    )


@pytest.mark.asyncio
async def test_list_outlines_serializes_dates_and_default_flag():
    outline = SimpleNamespace(
        id="outline-1",
        name="2026 考试大纲",
        year=2026,
        version="v1.0",
        description="全国统考大纲",
        status="active",
        is_default=1,
        release_date=date(2026, 1, 1),
        effective_date=None,
        created_at=datetime(2026, 1, 2, 3, 4, 5),
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_scalars_result([outline]))
    )

    result = await list_outlines(session)

    assert result == [
        {
            "id": "outline-1",
            "name": "2026 考试大纲",
            "year": 2026,
            "version": "v1.0",
            "description": "全国统考大纲",
            "status": "active",
            "is_default": True,
            "release_date": "2026-01-01",
            "effective_date": None,
            "created_at": "2026-01-02T03:04:05",
        }
    ]


@pytest.mark.asyncio
async def test_get_outline_chapters_builds_tree_and_keeps_orphan_as_root():
    root = SimpleNamespace(
        id="chapter-root",
        name="数据结构",
        code="DS",
        outline_code="一",
        level=1,
        parent_id=None,
        subject_id="subject-1",
        sort_order=0,
        description="基础数据结构",
        enhanced_description="掌握定义和应用",
        keywords=["Data Structure"],
        exam_guidance="先理解抽象数据类型",
    )
    child = SimpleNamespace(
        id="chapter-child",
        name="线性表",
        code="DS-1",
        outline_code="1",
        level=2,
        parent_id="chapter-root",
        subject_id="subject-1",
        sort_order=0,
        description="顺序表与链表",
        enhanced_description=None,
        keywords=["线性表"],
        exam_guidance=None,
    )
    orphan = SimpleNamespace(
        id="chapter-orphan",
        name="孤立章节",
        code=None,
        outline_code=None,
        level=2,
        parent_id="missing-parent",
        subject_id="subject-1",
        sort_order=1,
        description=None,
        enhanced_description=None,
        keywords=None,
        exam_guidance=None,
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=_scalars_result([root, child, orphan])
        )
    )

    result = await get_outline_chapters(
        session,
        "outline-1",
        subject_id="subject-1",
    )

    assert [chapter["id"] for chapter in result] == [
        "chapter-root",
        "chapter-orphan",
    ]
    assert result[0]["children"][0]["id"] == "chapter-child"
    assert result[0]["enhanced_description"] == "掌握定义和应用"
    assert result[0]["exam_guidance"] == "先理解抽象数据类型"
    assert result[1]["parent_id"] == "missing-parent"


@pytest.mark.asyncio
async def test_get_outline_subjects_maps_objective_and_guidance_status():
    link = SimpleNamespace(
        subject_id="subject-1",
        exam_objective="掌握数据结构基本原理",
        guidance_status="done",
        chapter_count=12,
    )
    subject = SimpleNamespace(
        name="数据结构",
        code="data_structure",
    )
    query_result = SimpleNamespace(
        all=Mock(return_value=[(link, subject)])
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=query_result)
    )

    result = await get_outline_subjects(session, "outline-1")

    assert result == [
        {
            "subject_id": "subject-1",
            "subject_name": "数据结构",
            "subject_code": "data_structure",
            "exam_objective": "掌握数据结构基本原理",
            "guidance_status": "done",
            "chapter_count": 12,
        }
    ]
