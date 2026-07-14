import pytest

from app.modules.catalog.outline_llm_parser import (
    extract_outline_llm_json,
    repair_truncated_json,
)
from app.modules.catalog.outline_tree import (
    collect_outline_leaves,
    count_outline_nodes,
    max_outline_depth,
    normalize_outline_chapters,
)


def test_extract_outline_llm_json_accepts_fence_comments_and_trailing_commas():
    result = extract_outline_llm_json(
        """
解析结果如下：
```json
{
  // 科目章节
  "chapters": [
    {"name": "线性表",},
  ],
  /* 忽略说明 */
  "exam_objective": "掌握基础",
}
```
""",
    )

    assert result == {
        "chapters": [{"name": "线性表"}],
        "exam_objective": "掌握基础",
    }


def test_extract_outline_llm_json_repairs_truncated_array_string():
    result = extract_outline_llm_json('{"items":["完整","截断')

    assert result == {"items": ["完整"]}


def test_repair_truncated_json_supplies_missing_object_value():
    repaired = repair_truncated_json('{"exam_objective":')

    assert repaired == '{"exam_objective": null}'


def test_extract_outline_llm_json_falls_back_to_python_literal():
    result = extract_outline_llm_json(
        "{'chapters': [{'name': '数据结构'}], 'enabled': True}"
    )

    assert result == {
        "chapters": [{"name": "数据结构"}],
        "enabled": True,
    }


@pytest.mark.parametrize("text", ["", "不是 JSON"])
def test_extract_outline_llm_json_rejects_unusable_content(text):
    with pytest.raises(ValueError):
        extract_outline_llm_json(text)


def test_normalize_outline_chapters_cleans_nested_llm_fields():
    normalized = normalize_outline_chapters(
        [
            {
                "title": " 线性表 ",
                "outline_code": 1.1,
                "description": 123,
                "enhanced_description": f" {'重' * 1001} ",
                "keywords": [" 数组 ", "", 0, "顺序表"],
                "cross_references": [{"target_chapter_id": "chapter-2"}],
                "children": [{"name": " 顺序表 "}],
            },
            "无效节点",
            {"name": ""},
        ]
    )

    assert len(normalized) == 1
    root = normalized[0]
    assert root["name"] == "线性表"
    assert root["outline_code"] == "1.1"
    assert root["description"] == "123"
    assert len(root["enhanced_description"]) == 1000
    assert root["keywords"] == ["数组", "顺序表"]
    assert root["cross_references"] == [{"target_chapter_id": "chapter-2"}]
    assert root["sort_order"] == 0
    assert root["children"][0]["name"] == "顺序表"


def test_outline_tree_helpers_count_depth_and_collect_leaves():
    leaf_b = {"name": "B", "children": []}
    leaf_d = {"name": "D", "children": []}
    leaf_e = {"name": "E", "children": []}
    chapters = [
        {
            "name": "A",
            "children": [
                leaf_b,
                {"name": "C", "children": [leaf_d]},
            ],
        },
        leaf_e,
    ]

    assert count_outline_nodes(chapters) == 5
    assert max_outline_depth(chapters) == 3
    assert max_outline_depth([]) == 0
    assert collect_outline_leaves(chapters) == [leaf_b, leaf_d, leaf_e]
