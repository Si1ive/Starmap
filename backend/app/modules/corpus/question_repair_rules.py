"""题目 LLM 修复的来源文本与安全替换规则。"""

from __future__ import annotations

import re
from typing import Any, Dict, List


def collect_target_source_text(question: Dict[str, Any]) -> str:
    """收集目标题自身可用于逐字核验的原始文本。"""
    parts = [
        str(question.get(key) or "")
        for key in ("raw_text", "stem", "content")
        if question.get(key)
    ]
    for block in question.get("blocks") or []:
        text = block_text(block)
        if text:
            parts.append(text)
    return "\n".join(parts)


def collect_context_source_text(
    questions: List[Dict[str, Any]],
    index: int,
) -> str:
    """收集目标题及前后题的三题上下文文本。"""
    parts: List[str] = []
    for question in questions[max(0, index - 1) : min(len(questions), index + 2)]:
        for key in ("raw_text", "stem", "content"):
            value = question.get(key)
            if value:
                parts.append(str(value))
        for option in question.get("options") or []:
            text = option.get("text") if isinstance(option, dict) else None
            if text:
                parts.append(str(text))
        for block in question.get("blocks") or []:
            text = block_text(block)
            if text:
                parts.append(text)
    return "\n".join(parts)


def normalize_source_text(text: str) -> str:
    """移除空白，供 MinerU 文本逐字包含关系核验。"""
    return re.sub(r"[\s　]+", "", text or "")


def text_exists_in_source(text: str, source_text: str) -> bool:
    """判断文本去空白后是否存在于来源文本。"""
    normalized = normalize_source_text(text)
    return bool(normalized and normalized in normalize_source_text(source_text))


def is_safe_repaired_stem(
    current_stem: str,
    repaired_stem: str,
) -> bool:
    """仅允许从当前题干中删除被误粘的内容，不接受改写。"""
    if not repaired_stem:
        return False
    current_normalized = normalize_source_text(current_stem)
    repaired_normalized = normalize_source_text(repaired_stem)
    return bool(
        repaired_normalized
        and current_normalized
        and repaired_normalized in current_normalized
    )


def is_safe_option_replacement(
    current_text: str,
    repaired_text: str,
    source_text: str,
) -> bool:
    """仅接受来自目标题原文的更长选项补全。"""
    current_normalized = normalize_source_text(current_text)
    repaired_normalized = normalize_source_text(repaired_text)
    if (
        not current_normalized
        or len(repaired_normalized) <= len(current_normalized)
        or not text_exists_in_source(repaired_text, source_text)
    ):
        return False
    if len(current_normalized) == 1:
        return current_normalized in repaired_normalized
    return repaired_normalized.startswith(
        current_normalized
    ) or repaired_normalized.endswith(current_normalized)


def block_text(block: Any) -> str:
    if isinstance(block, dict):
        value = block.get("content_text") or block.get("content_md") or ""
    else:
        value = (
            getattr(block, "content_text", None)
            or getattr(block, "content_md", None)
            or ""
        )
    return str(value) if value else ""


__all__ = [
    "collect_context_source_text",
    "collect_target_source_text",
    "is_safe_option_replacement",
    "is_safe_repaired_stem",
    "normalize_source_text",
    "text_exists_in_source",
]
