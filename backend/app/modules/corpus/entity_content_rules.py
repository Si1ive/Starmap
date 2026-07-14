"""语料实体入库前的选项、知识点文本和答案解析规则。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.modules.corpus.question_validation import get_option_label


def strip_leading_option_marker(
    text: str,
    expected_label: Optional[str] = None,
) -> str:
    """清理选项文本中重复或畸形的 MinerU 标记。"""
    cleaned = (text or "").strip()
    if expected_label:
        cleaned = re.sub(
            rf"^\s*{re.escape(expected_label.upper())}\s*"
            r"(?:[.．、:：。]|<sub>\s*[.．、:：。]\s*</sub>)\s*",
            "",
            cleaned,
        ).strip()
    malformed_sub = re.match(r"^\s*<sub>\s*[.．、:：。]\s*", cleaned)
    if malformed_sub:
        cleaned = cleaned[malformed_sub.end() :]
        cleaned = re.sub(
            r"^([^<]{0,60})</sub>",
            r"\1",
            cleaned,
            count=1,
        ).strip()
    return re.sub(r"^\s*[.．、:：。]\s*", "", cleaned).strip()


def normalize_options(
    options: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """统一选项键名、去重并保留抽取来源。"""
    normalized: List[Dict[str, Any]] = []
    seen_labels = set()
    for option in options or []:
        label = get_option_label(option)
        text = str(option.get("text") or option.get("content") or "").strip()
        text = strip_leading_option_marker(
            text,
            expected_label=label,
        )
        if not label or not text or label in seen_labels:
            continue
        normalized_option = {
            "key": label,
            "label": label,
            "option_label": label,
            "text": text,
        }
        if option.get("source") in {"extracted", "ai_generated"}:
            normalized_option["source"] = option["source"]
        normalized.append(normalized_option)
        seen_labels.add(label)
    return normalized


def extract_topic_terms(title: str, content: str) -> List[str]:
    """提取旧版入库流程使用的轻量主题词。"""
    terms = set()

    if title:
        clean_title = title.strip()
        for prefix in ["第", "章", "节", "、", "。", "：", ":", " "]:
            clean_title = clean_title.replace(prefix, " ")
        for word in clean_title.split():
            if len(word) >= 2:
                terms.add(word)

    if content:
        quoted = re.findall(
            r'[「『“"]([^」』”"]+)[」』”"]',
            content,
        )
        for quoted_term in quoted:
            if 2 <= len(quoted_term) <= 20:
                terms.add(quoted_term)

    return list(terms)[:20]


def build_knowledge_content(content_blocks: List[Any]) -> str:
    """优先使用 Markdown，并按段落拼接非空知识点 block。"""
    content_parts = []
    for block in content_blocks:
        text = (
            getattr(block, "content_md", None)
            or getattr(block, "content_text", None)
            or ""
        )
        if text.strip():
            content_parts.append(text.strip())
    return "\n\n".join(content_parts)


def extract_answers_from_blocks(blocks: List[Any]) -> Dict[str, str]:
    """只从答案区解析带题号的客观答案。"""
    answer_header_re = re.compile(
        r"(参考答案|答案与解析|答案速查|答案及解析|^\s*答案\s*$)"
    )
    text_parts: List[str] = []
    in_answer_zone = False
    for block in blocks:
        text = (
            getattr(block, "content_text", None)
            or getattr(block, "content_md", None)
            or ""
        ).strip()
        if not text:
            continue
        if not in_answer_zone and answer_header_re.search(text):
            in_answer_zone = True
            tail = answer_header_re.sub(" ", text).strip()
            if tail:
                text_parts.append(tail)
            continue
        if in_answer_zone:
            text_parts.append(text)
    if not in_answer_zone:
        return {}

    answer_text = "\n".join(text_parts)
    pair_re = re.compile(
        r"(?<!\d)(\d{1,3})\s*[.．、:：)）]\s*"
        r"([A-Da-d]{1,4}|对|错|正确|错误|√|×|T|F|是|否)"
    )
    return {
        match.group(1).strip(): match.group(2).strip().upper()
        for match in pair_re.finditer(answer_text)
    }


__all__ = [
    "build_knowledge_content",
    "extract_answers_from_blocks",
    "extract_topic_terms",
    "normalize_options",
    "strip_leading_option_marker",
]
