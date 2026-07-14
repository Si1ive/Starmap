"""选择题选项标记识别与文本切分规则。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


OPTION_SEPARATOR_RE = re.compile(
    r"(?:\s*(?:[.．、:：。]|<sub>\s*[.．、:：。]\s*</sub>)\s*|\s+)(?=\S)"
)
# 408 单选恒为 A-D。放宽到 A-H 会把图 G、访问位 R、修改位 M 等题干符号
# 误判为选项标记。
OPTION_MARKER_RE = re.compile(
    r"([A-D])"
    r"(?:\s*(?:[.．、:：。]|<sub>\s*[.．、:：。]\s*</sub>)\s*|\s+)"
    r"(?=\S)"
)
OPTION_BLOCK_RE = re.compile(
    r"^\s*([A-D])"
    r"(?:\s*(?:[.．、:：。]|<sub>\s*[.．、:：。]\s*</sub>)\s*|\s+)"
    r"(?=\S)"
)
CHOICE_BLANK_RE = re.compile(
    r"[（(]\s*(?:\)|）|_|　|\.{2,}|…{1,2})?\s*[）)]"
)


def has_inline_options(text: str) -> bool:
    """判断同一文本块中是否包含从 A 开始的多个选项标记。"""
    labels = {
        match.group(1).upper()
        for match in OPTION_MARKER_RE.finditer(text or "")
    }
    return "A" in labels and len(labels) >= 2


def find_inline_option_start(text: str) -> int:
    """返回选项 A 标记在文本中的起始下标；找不到返回 -1。"""
    for match in OPTION_MARKER_RE.finditer(text or ""):
        if match.group(1).upper() == "A":
            return match.start()
    return -1


def find_recoverable_inline_option(
    blocks: Sequence[Any],
) -> Optional[Tuple[int, int]]:
    """识别“A 粘在题干末尾、后续 B/C/D 分块”的 MinerU 常见输出。"""
    first_option_block_idx: Optional[int] = None
    first_option_label = ""
    for block_idx, block in enumerate(blocks):
        text = _block_text(block)
        match = OPTION_BLOCK_RE.match(text)
        if match:
            first_option_block_idx = block_idx
            first_option_label = match.group(1).upper()
            break

    if first_option_block_idx is None or first_option_label != "B":
        return None

    for block_idx in range(first_option_block_idx - 1, -1, -1):
        text = _block_text(blocks[block_idx])
        matches = [
            match
            for match in OPTION_MARKER_RE.finditer(text)
            if match.group(1).upper() == "A"
        ]
        if matches:
            last_match = matches[-1]
            start = last_match.start(1)
            if start > 0 and text[last_match.end():].strip():
                return block_idx, start
        if re.match(
            r"^\s*(\d{1,3})(?:\s*[.、．。]\s*|\s+)(?=\S)",
            text,
        ):
            break
    return None


def parse_options_from_text(text: str) -> List[Dict[str, str]]:
    """从连续选项文本中提取严格升序的 A-D 选项。"""
    if not text:
        return []
    matches = list(OPTION_MARKER_RE.finditer(text))
    if not matches:
        return []

    # MinerU 可能重复输出末选项残块。首个非升序标记视为选项区结束，
    # 并作为最后一个有效选项的截断位置。
    valid: List[Any] = []
    last_ord = ord("A") - 1
    cutoff = len(text)
    for match in matches:
        if ord(match.group(1).upper()) > last_ord:
            valid.append(match)
            last_ord = ord(match.group(1).upper())
        else:
            cutoff = match.start(1)
            break

    options: List[Dict[str, str]] = []
    for index, match in enumerate(valid):
        label = match.group(1).upper()
        text_start = match.end()
        text_end = (
            valid[index + 1].start(1)
            if index + 1 < len(valid)
            else cutoff
        )
        option_text = _strip_option_marker(text[text_start:text_end])
        if not option_text:
            continue
        options.append(
            {
                "key": label,
                "label": label,
                "option_label": label,
                "text": option_text,
            }
        )

    return options if len(options) >= 2 else []


def _block_text(block: Any) -> str:
    return (
        getattr(block, "content_text", None)
        or getattr(block, "content_md", None)
        or ""
    ).strip()


def _strip_option_marker(text: str) -> str:
    stripped = (text or "").strip()
    stripped = re.sub(r"^\s*[.．、:：。]\s*", "", stripped)
    return stripped.strip()


__all__ = [
    "CHOICE_BLANK_RE",
    "OPTION_BLOCK_RE",
    "OPTION_MARKER_RE",
    "OPTION_SEPARATOR_RE",
    "find_inline_option_start",
    "find_recoverable_inline_option",
    "has_inline_options",
    "parse_options_from_text",
]
