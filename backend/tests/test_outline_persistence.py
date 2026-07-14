from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.catalog.outline_persistence import OutlinePersistence


def _single_result(item):
    return SimpleNamespace(scalar_one_or_none=Mock(return_value=item))


def _multiple_result(items):
    return SimpleNamespace(
        scalars=Mock(
            return_value=SimpleNamespace(
                all=Mock(return_value=items),
            )
        )
    )


@pytest.mark.asyncio
async def test_upsert_outline_meta_updates_existing_and_clears_other_default():
    outline = SimpleNamespace(
        id="outline-1",
        name="旧名称",
        description="保留描述",
        status="inactive",
        is_default=False,
    )
    other = SimpleNamespace(is_default=True)
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _single_result(outline),
                _multiple_result([other]),
            ]
        ),
        add=Mock(),
        flush=AsyncMock(),
    )

    result = await OutlinePersistence(db).upsert_outline_meta(
        name="新名称",
        year=2026,
        version="v1.0",
        description=None,
        set_default=True,
    )

    assert result is outline
    assert outline.name == "新名称"
    assert outline.description == "保留描述"
    assert outline.status == "active"
    assert outline.is_default is True
    assert other.is_default is False
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_upsert_outline_meta_can_preserve_document_import_description():
    outline = SimpleNamespace(
        id="outline-1",
        name="旧名称",
        description="人工维护的描述",
        status="active",
        is_default=False,
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_single_result(outline)),
        add=Mock(),
        flush=AsyncMock(),
    )

    await OutlinePersistence(db).upsert_outline_meta(
        name="文档大纲",
        year=2026,
        version="v1.0",
        description="从文档自动转换",
        set_default=False,
        update_description=False,
    )

    assert outline.name == "文档大纲"
    assert outline.description == "人工维护的描述"


@pytest.mark.asyncio
async def test_upsert_chapters_creates_nested_tree():
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _single_result(None),
                _single_result(None),
            ]
        ),
        add=Mock(),
        flush=AsyncMock(),
    )

    created, updated = await OutlinePersistence(db).upsert_chapters(
        subject_id="subject-1",
        outline_id="outline-1",
        chapters=[
            {
                "name": "数据结构",
                "children": [
                    {
                        "name": "线性表",
                        "description": "顺序表和链表",
                    }
                ],
            }
        ],
    )

    assert (created, updated) == (2, 0)
    root = db.add.call_args_list[0].args[0]
    child = db.add.call_args_list[1].args[0]
    assert root.parent_id is None
    assert root.level == 1
    assert child.parent_id == root.id
    assert child.level == 2
    assert child.description == "顺序表和链表"
    assert db.flush.await_count == 2


@pytest.mark.asyncio
async def test_upsert_chapters_updates_fields_and_validates_cross_references(
    monkeypatch,
):
    chapter = SimpleNamespace(
        outline_code="旧编号",
        code="OLD",
        aliases=["旧别名"],
        description="旧描述",
        enhanced_description="旧增强",
        keywords=["旧关键词"],
        cross_references=None,
        sort_order=9,
        status="inactive",
    )
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_single_result(chapter)),
        add=Mock(),
        flush=AsyncMock(),
    )
    validate = AsyncMock(
        return_value=[
            {
                "target_chapter_id": "chapter-2",
                "relation_type": "prerequisite",
            }
        ]
    )
    monkeypatch.setattr(
        "app.modules.catalog.outline_persistence.validate_cross_references",
        validate,
    )

    created, updated = await OutlinePersistence(db).upsert_chapters(
        subject_id="subject-1",
        outline_id="outline-1",
        chapters=[
            {
                "name": "进程管理",
                "outline_code": "2.1",
                "code": "OS-2.1",
                "aliases": ["进程"],
                "description": "进程状态与调度",
                "enhanced_description": "常考状态转换",
                "keywords": ["Process"],
                "cross_references": [
                    {
                        "target_chapter_id": "chapter-2",
                        "relation_type": "prerequisite",
                    }
                ],
                "sort_order": 2,
            }
        ],
    )

    assert (created, updated) == (0, 1)
    assert chapter.outline_code == "2.1"
    assert chapter.code == "OS-2.1"
    assert chapter.aliases == ["进程"]
    assert chapter.description == "进程状态与调度"
    assert chapter.enhanced_description == "常考状态转换"
    assert chapter.keywords == ["Process"]
    assert chapter.cross_references[0]["target_chapter_id"] == "chapter-2"
    assert chapter.sort_order == 2
    assert chapter.status == "active"
    validate.assert_awaited_once()
