"""考试大纲文本和 JSON 输入解析。"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple


# 编号匹配（带层级权重）
NUMBER_PATTERNS: List[Tuple[re.Pattern, int]] = [
    # 第X章/第X部分（最高级）
    (re.compile(r"^\s*第\s*[一二三四五六七八九十百千万零\d]+\s*[章部篇]"), 1),
    # 中文一、二、三
    (re.compile(r"^\s*[一二三四五六七八九十]+\s*[、.]"), 1),
    # 1.1.1 类阿拉伯数字编号
    (re.compile(r"^\s*\d+(?:\.\d+){2,}"), 3),
    (re.compile(r"^\s*\d+\.\d+"), 2),
    (re.compile(r"^\s*\d+[.、]"), 1),
    # (一) (1)
    (re.compile(r"^\s*[（(]\s*[一二三四五六七八九十]+\s*[）)]"), 2),
    (re.compile(r"^\s*[（(]\s*\d+\s*[）)]"), 3),
    # ① ② 等圆圈数字
    (re.compile(r"^\s*[①②③④⑤⑥⑦⑧⑨⑩]"), 3),
]

# 编号清理（去除编号留下纯名称）
NUMBER_STRIP_RE = re.compile(
    r"^\s*(?:"
    r"第\s*[一二三四五六七八九十百千万零\d]+\s*[章部篇]\s*[:：、.]?"
    r"|[一二三四五六七八九十]+\s*[、.]"
    r"|\d+(?:\.\d+)*\s*[、.]?"
    r"|[（(]\s*[一二三四五六七八九十\d]+\s*[）)]"
    r"|[①②③④⑤⑥⑦⑧⑨⑩]"
    r")\s*"
)


def detect_outline_level(line: str) -> int:
    """根据行首编号或缩进推测层级（1=一级，越大越深）。"""
    stripped = line.lstrip()
    indent = len(line) - len(stripped)

    for pattern, level_hint in NUMBER_PATTERNS:
        if pattern.match(stripped):
            match = re.match(r"^\s*(\d+(?:\.\d+)*)", stripped)
            if match:
                return max(1, match.group(1).count(".") + 1)
            return level_hint

    if indent >= 4:
        return 3
    if indent >= 2:
        return 2
    return 1


def extract_outline_code(line: str) -> Optional[str]:
    """从行首抽出大纲编号。"""
    match = re.match(r"^\s*(\d+(?:\.\d+)*)", line)
    if match:
        return match.group(1)
    match = re.match(
        r"^\s*(第\s*[一二三四五六七八九十百千万零\d]+\s*[章部篇])",
        line,
    )
    if match:
        return match.group(1).replace(" ", "")
    match = re.match(r"^\s*([一二三四五六七八九十]+)\s*[、.]", line)
    if match:
        return match.group(1)
    match = re.match(
        r"^\s*[（(]\s*([一二三四五六七八九十\d]+)\s*[）)]",
        line,
    )
    if match:
        return f"({match.group(1)})"
    return None


def strip_outline_number(line: str) -> str:
    """剥离行首编号。"""
    return NUMBER_STRIP_RE.sub("", line.strip()).strip()


def parse_outline_text(text: str) -> List[Dict[str, Any]]:
    """将纯文本大纲解析为章节树。"""
    if not text or not text.strip():
        return []

    chapters_tree: List[Dict[str, Any]] = []
    stack: List[Tuple[int, List[Dict[str, Any]]]] = [(0, chapters_tree)]
    sort_order = 0

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue

        level = detect_outline_level(raw_line)
        name = strip_outline_number(raw_line)
        if not name:
            continue

        chapter = {
            "name": name[:200],
            "outline_code": extract_outline_code(raw_line),
            "sort_order": sort_order,
            "children": [],
        }
        sort_order += 1

        while stack and stack[-1][0] >= level:
            stack.pop()

        parent_children = stack[-1][1] if stack else chapters_tree
        parent_children.append(chapter)
        stack.append((level, chapter["children"]))

    return chapters_tree


def parse_outline_json(text: str) -> List[Dict[str, Any]]:
    """解析根级数组或包含 ``chapters`` 字段的 JSON 大纲。"""
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("chapters") or []
    raise ValueError("无效的 JSON 大纲格式")


def detect_outline_format(filename: str, content: str) -> str:
    """根据文件扩展名和内容探测大纲格式。"""
    name_lower = (filename or "").lower()
    if name_lower.endswith(".json"):
        return "json"
    if name_lower.endswith((".txt", ".md")):
        return "text"
    if content.lstrip()[:1] in "[{":
        return "json"
    return "text"
