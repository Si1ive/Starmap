"""大纲章节树的清洗和遍历工具。"""

from typing import Any, Dict, List


def normalize_outline_chapters(raw: Any) -> List[Dict[str, Any]]:
    """递归清洗 LLM 输出，并为同级节点补充稳定排序号。"""
    result: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return result

    for index, node in enumerate(raw):
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or node.get("title") or "").strip()
        if not name:
            continue

        enhanced_description = node.get("enhanced_description")
        if enhanced_description:
            enhanced_description = str(enhanced_description).strip()[:1000]

        keywords = node.get("keywords")
        if keywords:
            if isinstance(keywords, list):
                keywords = [
                    str(keyword).strip()
                    for keyword in keywords
                    if keyword
                ][:50]
            else:
                keywords = None

        result.append(
            {
                "name": name[:200],
                "outline_code": (
                    str(node.get("outline_code")).strip()[:50]
                    if node.get("outline_code")
                    else None
                ),
                "description": (
                    str(node.get("description")).strip()
                    if node.get("description")
                    else None
                ),
                "enhanced_description": enhanced_description,
                "keywords": keywords,
                "cross_references": (
                    node.get("cross_references")
                    if isinstance(node.get("cross_references"), list)
                    else None
                ),
                "sort_order": index,
                "children": normalize_outline_chapters(node.get("children") or []),
            }
        )
    return result


def count_outline_nodes(chapters: List[Dict[str, Any]]) -> int:
    """统计章节树全部节点数。"""
    return sum(
        1 + count_outline_nodes(chapter.get("children") or [])
        for chapter in chapters
    )


def max_outline_depth(
    chapters: List[Dict[str, Any]],
    current: int = 1,
) -> int:
    """返回章节树最大深度，空树深度为 0。"""
    if not chapters:
        return 0
    return max(
        max_outline_depth(chapter.get("children") or [], current + 1) or current
        for chapter in chapters
    )


def collect_outline_leaves(
    chapters: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """按树遍历顺序返回所有叶子节点。"""
    result: List[Dict[str, Any]] = []
    for chapter in chapters:
        children = chapter.get("children") or []
        if children:
            result.extend(collect_outline_leaves(children))
        else:
            result.append(chapter)
    return result
