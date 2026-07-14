"""题目组内题干、选项、媒体和题号提取规则。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.modules.corpus.question_layout_geometry import (
    PageStats,
    bbox_x0,
    bbox_x1,
    bbox_y0,
    bbox_y1,
)
from app.modules.corpus.question_option_rules import (
    OPTION_BLOCK_RE,
    find_inline_option_start,
    find_recoverable_inline_option,
    has_inline_options,
    parse_options_from_text,
)
from app.modules.corpus.question_type import is_subjective_question_text

QUESTION_NUMERIC_RE = re.compile(r"^\s*(\d{1,3})(?:\s*[.、．。]\s*|\s+)(?=\S)")
EMBEDDED_QUESTION_NUMERIC_RE = re.compile(
    r"(?<!\d)(\d{1,3})(?:\s*[.、．。]\s*|\s+)(?=\S)"
)
QUESTION_TITLE_RE = re.compile(r"^\s*第\s*([一二三四五六七八九十百千\d]+)\s*题")
QUESTION_PAREN_RE = re.compile(r"^\s*[（(]\s*(\d{1,3})\s*[）)]\s*\S+")
QUESTION_EXAMPLE_RE = re.compile(r"^\s*例\s*\d+")
QUESTION_CUE_RE = re.compile(
    r"[?？]|下列|以下|关于|若|设|已知|正确|错误|不是|可以|能够|应|属于|采用|"
    r"给出|求|计算|证明|说明|分析|为什么|多少|哪个|哪些|如果|判断"
)

OPTION_CONTINUATION_GAP_RATIO = 1.5
OPTION_CONTINUATION_LEFT_MARGIN = 30

_MEDIA_BLOCK_TYPES = {
    "figure",
    "table",
    "formula",
    "image",
    "chart",
}


def extract_stem(blocks: Sequence[Any]) -> str:
    """提取题干，并从选择题题干中剥离内联选项。"""
    if is_subjective_question_text(group_text(blocks)):
        return extract_full_stem(blocks)

    parts: List[str] = []
    in_options = False
    recoverable_inline = find_recoverable_inline_option(blocks)
    for block_index, block in enumerate(blocks):
        text = block_text(block)
        if not text:
            continue
        if OPTION_BLOCK_RE.match(text):
            in_options = True
        if in_options:
            continue

        block_type = block_type_name(block)
        if block_type in _MEDIA_BLOCK_TYPES:
            # MinerU 可能把题干文字和数据表放进同一个 table 块。
            if QUESTION_NUMERIC_RE.match(text):
                parts.append(text)
            continue

        if recoverable_inline and block_index == recoverable_inline[0]:
            stem_part = text[: recoverable_inline[1]].strip()
            if stem_part:
                parts.append(stem_part)
            in_options = True
            continue

        if has_inline_options(text):
            option_start = find_inline_option_start(text)
            if option_start > 0:
                stem_part = text[:option_start].strip()
                if stem_part:
                    parts.append(stem_part)
                in_options = True
                continue
        parts.append(text)
    return " ".join(parts)


def extract_options(
    blocks: Sequence[Any],
    page_stats: Mapping[int, PageStats],
) -> List[Dict[str, str]]:
    """从题目组提取选项，并合并紧邻末选项的跨块尾部文字。"""
    if is_subjective_question_text(group_text(blocks)):
        return []

    option_blocks: List[str] = []
    non_option_after: List[Any] = []
    last_option_block: Optional[Any] = None
    option_phase = False
    recoverable_inline = find_recoverable_inline_option(blocks)

    for block_index, block in enumerate(blocks):
        text = block_text(block)
        block_type = block_type_name(block)

        if recoverable_inline and block_index == recoverable_inline[0]:
            option_phase = True
            option_blocks.append(text[recoverable_inline[1] :])
            last_option_block = block
        elif OPTION_BLOCK_RE.match(text):
            option_phase = True
            option_blocks.append(text)
            last_option_block = block
        elif not option_phase and has_inline_options(text):
            option_start = find_inline_option_start(text)
            if option_start >= 0:
                option_phase = True
                option_blocks.append(text[option_start:])
                last_option_block = block
        elif (
            option_phase
            and block_type not in _MEDIA_BLOCK_TYPES
            and last_option_block is not None
            and should_append_to_last_option(
                last_option_block,
                block,
                page_stats,
            )
        ):
            non_option_after.append(block)

    if not option_blocks:
        return []

    options = parse_options_from_text(" ".join(option_blocks))
    if non_option_after and options:
        trailing_text = " ".join(
            block_text(block) for block in non_option_after
        ).strip()
        if trailing_text and not QUESTION_NUMERIC_RE.match(trailing_text):
            options[-1]["text"] = f"{options[-1]['text']} {trailing_text}"
    return options


def group_text(blocks: Sequence[Any]) -> str:
    """拼接题目组内所有非空文本。"""
    return " ".join(text for block in blocks if (text := block_text(block)))


def extract_full_stem(blocks: Sequence[Any]) -> str:
    """提取简答题完整题干，同时忽略纯媒体块。"""
    parts: List[str] = []
    for block in blocks:
        text = block_text(block)
        if not text:
            continue
        if block_type_name(
            block
        ) in _MEDIA_BLOCK_TYPES and not QUESTION_NUMERIC_RE.match(text):
            continue
        parts.append(text)
    return " ".join(parts)


def should_append_to_last_option(
    option_block: Any,
    continuation_block: Any,
    page_stats: Mapping[int, PageStats],
) -> bool:
    """判断普通文本块是否是末选项的紧邻续文。"""
    text = block_text(continuation_block)
    if not text:
        return False
    if (
        QUESTION_NUMERIC_RE.match(text)
        or QUESTION_PAREN_RE.match(text)
        or OPTION_BLOCK_RE.match(text)
    ):
        return False

    option_bbox = getattr(option_block, "bbox", None) or {}
    continuation_bbox = getattr(continuation_block, "bbox", None) or {}
    option_y1 = bbox_y1(option_bbox)
    continuation_y0 = bbox_y0(continuation_bbox)
    option_x0 = bbox_x0(option_bbox)
    option_x1 = bbox_x1(option_bbox)
    continuation_x0 = bbox_x0(continuation_bbox)

    if (
        option_y1 is not None
        and continuation_y0 is not None
        and continuation_y0 < option_y1
    ):
        return False

    page_no = (
        getattr(option_block, "page_no", None)
        or getattr(continuation_block, "page_no", None)
        or 1
    )
    stats = page_stats.get(page_no)
    if stats and option_y1 is not None and continuation_y0 is not None:
        gap = max(0.0, continuation_y0 - option_y1)
        gap_ratio = gap / max(stats.median_gap, 1.0)
        if gap_ratio >= OPTION_CONTINUATION_GAP_RATIO:
            return False

    if (
        option_x0 is not None
        and option_x1 is not None
        and continuation_x0 is not None
        and continuation_x0 > option_x1 + OPTION_CONTINUATION_LEFT_MARGIN
    ):
        return False
    return True


def extract_figures(blocks: Sequence[Any]) -> List[str]:
    """提取题目组内图、表、公式等媒体块 ID。"""
    figure_ids: List[str] = []
    for block in blocks:
        if block_type_name(block) not in _MEDIA_BLOCK_TYPES:
            continue
        block_id = getattr(block, "id", None)
        if block_id:
            figure_ids.append(block_id)
    return figure_ids


def extract_question_no(blocks: Sequence[Any]) -> Optional[int]:
    """提取数字题号、括号题号或“第 N 题”题号。"""
    for block in blocks:
        text = block_text(block)
        match = QUESTION_NUMERIC_RE.match(text)
        if match:
            return int(match.group(1))
        match = QUESTION_PAREN_RE.match(text)
        if match:
            return int(match.group(1))
        match = QUESTION_TITLE_RE.match(text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def classify_group(
    blocks: Sequence[Any],
    options: Sequence[Dict[str, str]],
    question_no: Optional[int],
) -> Tuple[str, str]:
    """根据选项、题号和疑问词判断题目组类别。"""
    if options and len(options) >= 2:
        return "question", "has_options"
    if question_no is not None:
        return "question", "has_question_no"
    if QUESTION_CUE_RE.search(group_text(blocks)):
        return "question", "has_cue"
    return "uncertain", "no_signal"


def block_text(block: Any) -> str:
    return (
        getattr(block, "content_text", None) or getattr(block, "content_md", None) or ""
    ).strip()


def block_type_name(block: Any) -> str:
    return (getattr(block, "block_type", "") or "").lower()


__all__ = [
    "EMBEDDED_QUESTION_NUMERIC_RE",
    "OPTION_CONTINUATION_GAP_RATIO",
    "OPTION_CONTINUATION_LEFT_MARGIN",
    "QUESTION_CUE_RE",
    "QUESTION_EXAMPLE_RE",
    "QUESTION_NUMERIC_RE",
    "QUESTION_PAREN_RE",
    "QUESTION_TITLE_RE",
    "classify_group",
    "extract_figures",
    "extract_full_stem",
    "extract_options",
    "extract_question_no",
    "extract_stem",
    "group_text",
    "should_append_to_last_option",
]
