"""Pure heading detection rules for document section extraction."""

import re
from typing import Any, Dict, List, Optional


HEADING_PATTERNS = [
    re.compile(r'^第[一二三四五六七八九十百千\d]+[章节目部]'),
    re.compile(r'^\d+(\.\d+)*\.?\s'),
    re.compile(r'^[IVXLC]+\.?\s'),
    re.compile(r'^[一二三四五六七八九十]+[、.．]'),
    re.compile(r'^[（(][一二三四五六七八九十]+[）)]'),
    re.compile(r'^(Chapter|Section|Part)\s+\d+', re.IGNORECASE),
]

LEVEL_KEYWORDS = {
    1: ['章', 'chapter', 'part', '部分'],
    2: ['节', 'section', '模块'],
    3: ['点', '小节', 'subsection'],
}

QUESTION_CUE_RE = re.compile(
    r'[?？]|下列|以下|关于|若|设|已知|正确|错误|不是|可以|能够|应|属于|采用|'
    r'给出|求|计算|证明|说明|分析|为什么|多少|哪个|哪些|如果|判断'
)
OPTION_MARKER_RE = re.compile(r'(^|[\n\r\t 　])[A-H]\s*[.．、:：]\s*\S+')
SCORED_QUESTION_RE = re.compile(
    r'^\s*\d{1,3}\s*[（(]\s*\d+(?:\.\d+)?\s*分\s*[）)]\s*\S+'
)


def looks_like_question_or_option(text: str) -> bool:
    """Return whether parser-labelled heading text is actually question content."""
    if OPTION_MARKER_RE.match(text):
        return True
    if SCORED_QUESTION_RE.match(text):
        return True
    if re.match(r'^\s*第\s*[一二三四五六七八九十百千\d]+\s*题', text):
        return True
    if re.match(r'^\s*[（(]\s*\d{1,3}\s*[）)]\s*\S+', text):
        return bool(QUESTION_CUE_RE.search(text)) or len(text) > 30
    if re.match(r'^\s*\d{1,3}\s*[.、．]\s*\S+', text):
        return (
            bool(QUESTION_CUE_RE.search(text))
            or len(text) > 40
            or bool(OPTION_MARKER_RE.search(text))
        )
    return False


def detect_heading_level(text: str, block_type: str) -> Optional[int]:
    """Return a detected heading level, or None for ordinary content."""
    text = text.strip()
    if not text or looks_like_question_or_option(text):
        return None

    if block_type in ('title', 'heading'):
        if len(text) > 120:
            return None
        if re.match(r'^第[一二三四五六七八九十百千\d]+章', text):
            return 1
        if re.match(r'^第[一二三四五六七八九十百千\d]+节', text):
            return 2
        match = re.match(r'^(\d+(?:\.\d+)*)\.?\s', text)
        if match:
            return len(match.group(1).split('.'))
        if re.match(r'^[IVXLC]+\.?\s', text):
            return 1
        if re.match(r'^[一二三四五六七八九十]+[、.．]', text):
            return 1
        if re.match(r'^[（(][一二三四五六七八九十]+[）)]', text):
            return 2
        return 1

    if block_type == 'paragraph':
        for pattern in HEADING_PATTERNS:
            if not pattern.match(text):
                continue
            if re.match(r'^第[一二三四五六七八九十百千\d]+章', text):
                return 1
            if re.match(r'^第[一二三四五六七八九十百千\d]+节', text):
                return 2
            match = re.match(r'^(\d+(?:\.\d+)*)\.?\s', text)
            if match:
                return len(match.group(1).split('.'))
            return 1

        if len(text) < 100:
            normalized = text.lower()
            for level, keywords in LEVEL_KEYWORDS.items():
                if any(keyword in normalized for keyword in keywords):
                    return level

    return None


def build_section_path(
    sections: List[Dict[str, Any]],
    current_level: int,
    current_title: str,
) -> str:
    """Build a stable parent path from previously opened sections."""
    path_parts = []

    for index in range(len(sections) - 1, -1, -1):
        if sections[index]['level'] < current_level:
            path_parts.insert(0, sections[index]['title'])
            current_level = sections[index]['level']
            if current_level == 1:
                break

    path_parts.append(current_title)
    return ' > '.join(path_parts)


# Backward-compatible private names for historical imports.
_looks_like_question_or_option = looks_like_question_or_option
_detect_heading_level = detect_heading_level
_build_section_path = build_section_path
