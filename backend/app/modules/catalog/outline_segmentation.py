"""大纲文本的科目边界识别与长内容分块。"""

import re
from typing import Dict, List, Tuple


SUBJECT_ALIASES: Dict[str, str] = {
    "数据结构": "data_structure",
    "计算机组成原理": "computer_organization",
    "计算机组成": "computer_organization",
    "计组": "computer_organization",
    "操作系统": "operating_system",
    "计算机网络": "computer_network",
    "计网": "computer_network",
}

CHAPTER_HEADING_PATTERN = re.compile(
    r"^\s*(?:"
    r"第[一二三四五六七八九十百千万零\d]+章"
    r"|[一二三四五六七八九十]+\s*[、.]"
    r"|\d+\s*[、.]"
    r")"
)


def segment_outline_subjects(markdown: str) -> List[Tuple[str, int, int]]:
    """按首次出现的科目别名返回文本区间；少于两门课时返回空列表。"""
    hits: List[Tuple[int, str]] = []
    for alias, code in SUBJECT_ALIASES.items():
        for match in re.finditer(re.escape(alias), markdown):
            hits.append((match.start(), code))
    if not hits:
        return []

    first_positions: Dict[str, int] = {}
    for position, code in sorted(hits):
        if code not in first_positions:
            first_positions[code] = position
    if len(first_positions) < 2:
        return []

    ordered = sorted(first_positions.items(), key=lambda item: item[1])
    return [
        (
            code,
            position,
            ordered[index + 1][1]
            if index + 1 < len(ordered)
            else len(markdown),
        )
        for index, (code, position) in enumerate(ordered)
    ]


def split_outline_chapter_chunks(
    content: str,
    max_chunk_size: int = 30000,
) -> List[str]:
    """内容超过目标大小后，只在后续一级章节标题处开始新块。"""
    chunks: List[str] = []
    current_chunk: List[str] = []
    current_size = 0

    for line in content.split("\n"):
        line_size = len(line) + 1
        should_split = (
            CHAPTER_HEADING_PATTERN.match(line)
            and current_chunk
            and current_size + line_size > max_chunk_size
        )
        if should_split:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_size = line_size
        else:
            current_chunk.append(line)
            current_size += line_size

    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks if chunks else [content]
