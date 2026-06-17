"""
文本清洗工具：处理 MinerU/Docling 输出里的 <sub>/<sup> 标签和多余空白。

被 document_parse_service 在持久化 block 时调用，也被 entity_extraction_service
在抽取入口时兜底调用（即兼容旧数据）。
"""

import re
from typing import Optional

_SUB_UNICODE_MAP = {
    '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
    '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
    '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
    'a': 'ₐ', 'e': 'ₑ', 'h': 'ₕ', 'i': 'ᵢ', 'j': 'ⱼ',
    'k': 'ₖ', 'l': 'ₗ', 'm': 'ₘ', 'n': 'ₙ', 'o': 'ₒ',
    'p': 'ₚ', 'r': 'ᵣ', 's': 'ₛ', 't': 'ₜ', 'u': 'ᵤ',
    'v': 'ᵥ', 'x': 'ₓ',
}

_SUP_UNICODE_MAP = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
    'a': 'ᵃ', 'b': 'ᵇ', 'c': 'ᶜ', 'd': 'ᵈ', 'e': 'ᵉ',
    'f': 'ᶠ', 'g': 'ᵍ', 'h': 'ʰ', 'i': 'ⁱ', 'j': 'ʲ',
    'k': 'ᵏ', 'l': 'ˡ', 'm': 'ᵐ', 'n': 'ⁿ', 'o': 'ᵒ',
    'p': 'ᵖ', 'r': 'ʳ', 's': 'ˢ', 't': 'ᵗ', 'u': 'ᵘ',
    'v': 'ᵛ', 'w': 'ʷ', 'x': 'ˣ', 'y': 'ʸ', 'z': 'ᶻ',
}

_PUNCT_SUB_REPLACEMENTS = [
    (re.compile(r'<sub>\s*[．。]\s*</sub>', re.IGNORECASE), '。'),
    (re.compile(r'<sub>\s*[，,]\s*</sub>', re.IGNORECASE), '，'),
    (re.compile(r'<sub>\s*[；;]\s*</sub>', re.IGNORECASE), '；'),
    (re.compile(r'<sub>\s*[：:]\s*</sub>', re.IGNORECASE), '：'),
    (re.compile(r'<sub>\s*[！!]\s*</sub>', re.IGNORECASE), '！'),
    (re.compile(r'<sub>\s*[？?]\s*</sub>', re.IGNORECASE), '？'),
    (re.compile(r'<sub>\s*[、]\s*</sub>', re.IGNORECASE), '、'),
]

_SUB_TAG_RE = re.compile(r'<sub>(.*?)</sub>', re.IGNORECASE | re.DOTALL)
_SUP_TAG_RE = re.compile(r'<sup>(.*?)</sup>', re.IGNORECASE | re.DOTALL)
_DANGLING_SUB_RE = re.compile(r'</?sub\s*/?>', re.IGNORECASE)
_DANGLING_SUP_RE = re.compile(r'</?sup\s*/?>', re.IGNORECASE)


def _convert_with_map(inner: str, mapping: dict, fallback_prefix: str) -> str:
    inner = inner.strip()
    if not inner:
        return ''
    if all(ch.lower() in mapping for ch in inner):
        return ''.join(mapping[ch.lower()] for ch in inner)
    return f'{fallback_prefix}{inner}'


def normalize_whitespace(text: str) -> str:
    """合并水平空白、清行尾空白、压缩多连续换行、整体 strip。"""
    if not text:
        return text
    text = re.sub(r'[ \t 　]+', ' ', text)
    text = re.sub(r' *\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def clean_block_text(text: Optional[str]) -> Optional[str]:
    """
    清洗 block 文本：
    1. <sub>标点</sub> → 真实标点（。，；：等）
    2. <sub>数字/英文/可映射字符</sub> → Unicode 下标（₂ ₙ ₓ）
    3. <sup> 同上转上标
    4. 不可映射的多字符内容降级为 _xxx / ^xxx
    5. 残留闭合/开标签清掉
    6. 规范化空白
    """
    if not text:
        return text

    cleaned = text
    for pattern, replacement in _PUNCT_SUB_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)

    cleaned = _SUB_TAG_RE.sub(
        lambda m: _convert_with_map(m.group(1), _SUB_UNICODE_MAP, '_'),
        cleaned,
    )
    cleaned = _SUP_TAG_RE.sub(
        lambda m: _convert_with_map(m.group(1), _SUP_UNICODE_MAP, '^'),
        cleaned,
    )

    cleaned = _DANGLING_SUB_RE.sub('', cleaned)
    cleaned = _DANGLING_SUP_RE.sub('', cleaned)

    return normalize_whitespace(cleaned)
