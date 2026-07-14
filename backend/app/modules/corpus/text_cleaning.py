"""
文本清洗工具：处理 MinerU 输出里的 <sub>/<sup> 标签和多余空白。

策略说明：
- <sub>标点</sub> 是 MinerU 误识别（"。" 被切成下标），还原成真实标点；
- 其余 <sub>...</sub> 和 <sup>...</sup> 直接剥离标签、保留内部文本（项目场景是计算机考试，
  极少有真实的上下标，强行转 Unicode 反而会把误识别内容误判为下标，得不偿失）；
- 顺带规范化空白（合并多余空格、清行尾空白、压缩多空行）。

被 document_store 在持久化 block 时调用，也被 entity_extraction_pipeline
在抽取入口时兜底调用（兼容旧数据）。
"""

import re
from typing import Optional

_PUNCT_SUB_REPLACEMENTS = [
    (re.compile(r'<sub>\s*[．。]\s*</sub>', re.IGNORECASE), '。'),
    (re.compile(r'<sub>\s*[，,]\s*</sub>', re.IGNORECASE), '，'),
    (re.compile(r'<sub>\s*[；;]\s*</sub>', re.IGNORECASE), '；'),
    (re.compile(r'<sub>\s*[：:]\s*</sub>', re.IGNORECASE), '：'),
    (re.compile(r'<sub>\s*[！!]\s*</sub>', re.IGNORECASE), '！'),
    (re.compile(r'<sub>\s*[？?]\s*</sub>', re.IGNORECASE), '？'),
    (re.compile(r'<sub>\s*[、]\s*</sub>', re.IGNORECASE), '、'),
]

# 任意 sub/sup 标签（含闭合）；剥离后保留内部内容
_SUB_TAG_RE = re.compile(r'<sub>(.*?)</sub>', re.IGNORECASE | re.DOTALL)
_SUP_TAG_RE = re.compile(r'<sup>(.*?)</sup>', re.IGNORECASE | re.DOTALL)
# 残留的孤立开/闭标签
_DANGLING_SUB_RE = re.compile(r'</?sub\s*/?>', re.IGNORECASE)
_DANGLING_SUP_RE = re.compile(r'</?sup\s*/?>', re.IGNORECASE)


def normalize_whitespace(text: str) -> str:
    """合并水平空白、清行尾空白、压缩多连续换行、整体 strip。"""
    if not text:
        return text
    text = re.sub(r'[ \t 　]+', ' ', text)
    text = re.sub(r' *\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def clean_block_text(text: Optional[str]) -> Optional[str]:
    """
    清洗 block 文本：
    1. <sub>标点</sub> → 真实标点（解析器误识别校正）
    2. 其余 <sub>...</sub> / <sup>...</sup> → 剥离标签，保留内部文本
    3. 残留闭合/开标签清掉
    4. 规范化空白
    """
    if not text:
        return text

    cleaned = text
    for pattern, replacement in _PUNCT_SUB_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)

    cleaned = _SUB_TAG_RE.sub(lambda m: m.group(1), cleaned)
    cleaned = _SUP_TAG_RE.sub(lambda m: m.group(1), cleaned)

    cleaned = _DANGLING_SUB_RE.sub('', cleaned)
    cleaned = _DANGLING_SUP_RE.sub('', cleaned)

    return normalize_whitespace(cleaned)
