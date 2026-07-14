from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.catalog.outline_document_sections import (
    build_outline_tree_from_sections,
    load_outline_tree_from_document_sections,
)


def _section(level, title):
    return SimpleNamespace(level=level, title=title)


def _scalars_result(items):
    return SimpleNamespace(
        scalars=Mock(
            return_value=SimpleNamespace(
                all=Mock(return_value=items),
            )
        )
    )


def test_build_outline_tree_from_sections_uses_order_and_heading_levels():
    sections = [
        _section(1, "第一章 数据结构"),
        _section(2, "1.1 线性表"),
        _section(3, "1.1.1 顺序表"),
        _section(2, "1.2 树"),
        _section(1, "第二章 算法"),
    ]

    result = build_outline_tree_from_sections(sections)

    assert [chapter["name"] for chapter in result] == [
        "第一章 数据结构",
        "第二章 算法",
    ]
    assert result[0]["children"][0]["name"] == "1.1 线性表"
    assert (
        result[0]["children"][0]["children"][0]["name"]
        == "1.1.1 顺序表"
    )
    assert result[0]["children"][1]["name"] == "1.2 树"
    assert result[0]["children"][0]["outline_code"] == "1.1"
    assert result[0]["children"][1]["sort_order"] == 3


def test_build_outline_tree_from_sections_normalizes_level_and_title_length():
    long_title = "1. " + ("章节" * 120)
    sections = [
        _section(None, "  无层级标题  "),
        _section(0, long_title),
        _section(3, "3.1 深层标题"),
    ]

    result = build_outline_tree_from_sections(sections)

    assert [chapter["name"] for chapter in result] == [
        "无层级标题",
        long_title[:200],
    ]
    assert result[1]["children"][0]["name"] == "3.1 深层标题"
    assert len(result[1]["name"]) == 200


@pytest.mark.asyncio
async def test_load_outline_tree_from_document_sections_rejects_empty_document():
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_scalars_result([]))
    )

    with pytest.raises(ValueError, match="文档没有可用的标题树"):
        await load_outline_tree_from_document_sections(
            session,
            "document-1",
        )


@pytest.mark.asyncio
async def test_load_outline_tree_from_document_sections_returns_converted_tree():
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=_scalars_result(
                [
                    _section(1, "第一章 操作系统"),
                    _section(2, "1.1 进程管理"),
                ]
            )
        )
    )

    result = await load_outline_tree_from_document_sections(
        session,
        "document-1",
    )

    assert result[0]["name"] == "第一章 操作系统"
    assert result[0]["children"][0]["outline_code"] == "1.1"
