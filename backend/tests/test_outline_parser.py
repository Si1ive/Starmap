import json

import pytest

from app.modules.catalog.outline_import_service import OutlineImportService
from app.modules.catalog.outline_parser import (
    detect_outline_format,
    extract_outline_code,
    parse_outline_json,
    parse_outline_text,
)


def test_parse_outline_text_builds_numbered_hierarchy():
    chapters = parse_outline_text(
        """
        # 导入说明
第一章 数据结构
1.1 线性表
1.1.1 顺序表
1.2 栈和队列
第二章 算法
""",
    )

    assert [chapter["name"] for chapter in chapters] == ["数据结构", "算法"]
    assert chapters[0]["outline_code"] == "第一章"
    assert chapters[0]["sort_order"] == 0
    assert [chapter["name"] for chapter in chapters[0]["children"]] == [
        "线性表",
        "栈和队列",
    ]
    assert chapters[0]["children"][0]["children"] == [
        {
            "name": "顺序表",
            "outline_code": "1.1.1",
            "sort_order": 2,
            "children": [],
        }
    ]
    assert chapters[1]["sort_order"] == 4


def test_parse_outline_text_uses_indentation_for_unnumbered_lines():
    chapters = parse_outline_text(
        """
操作系统
  进程管理
    进程调度
""",
    )

    assert chapters == [
        {
            "name": "操作系统",
            "outline_code": None,
            "sort_order": 0,
            "children": [
                {
                    "name": "进程管理",
                    "outline_code": None,
                    "sort_order": 1,
                    "children": [
                        {
                            "name": "进程调度",
                            "outline_code": None,
                            "sort_order": 2,
                            "children": [],
                        }
                    ],
                }
            ],
        }
    ]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("1.2.3 处理器", "1.2.3"),
        ("第 二 章 操作系统", "第二章"),
        ("三、计算机网络", "三"),
        ("（四）数据库", "(四)"),
        ("无编号章节", None),
    ],
)
def test_extract_outline_code_supports_common_numbering(line, expected):
    assert extract_outline_code(line) == expected


def test_parse_outline_json_accepts_list_and_chapters_wrapper():
    chapters = [{"name": "数据结构", "children": []}]

    assert parse_outline_json(json.dumps(chapters, ensure_ascii=False)) == chapters
    assert parse_outline_json(
        json.dumps({"chapters": chapters}, ensure_ascii=False)
    ) == chapters


def test_parse_outline_json_rejects_scalar_root():
    with pytest.raises(ValueError, match="无效的 JSON 大纲格式"):
        parse_outline_json('"数据结构"')


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("outline.JSON", "not-json", "json"),
        ("outline.md", '{"chapters": []}', "text"),
        ("", '  {"chapters": []}', "json"),
        ("outline.bin", "[1, 2]", "json"),
        ("outline.bin", "第一章 数据结构", "text"),
    ],
)
def test_detect_outline_format_prefers_known_extension_then_content(
    filename,
    content,
    expected,
):
    assert detect_outline_format(filename, content) == expected


@pytest.mark.asyncio
async def test_outline_import_preview_uses_parser_and_reports_tree_metrics():
    service = OutlineImportService(db=None)

    result = await service.preview(
        "第一章 数据结构\n1.1 线性表\n1.1.1 顺序表",
        filename="outline.txt",
    )

    assert result["format"] == "text"
    assert result["total_chapters"] == 3
    assert result["max_depth"] == 3
