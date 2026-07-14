"""
语料 Block 内容类型分类器

为混排文档（教材正文 + 习题混在一起）的每个 block 标记类型，让知识点和题目两条
提取链路各取所需，避免重叠误判。

类型：
- heading: 章节标题
- knowledge: 概念定义 / 段落正文 / 列表（适合作为知识点）
- question_stem: 题干
- question_option: 选择题选项块
- answer: 答案 / 解析
- table / figure / formula: 资产块（独立处理）
- noise: 页眉页脚等噪声

策略：
1. 第一遍：每个 block 单独按特征打分得到候选类型
2. 第二遍：基于上下文调整（题号邻居、章节范围、答案缩排等）
3. 可选 LLM 兜底：对仍未分类的 ambiguous 块批量送 LLM 判别
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger

logger = get_logger(__name__)


# ===== 正则信号 =====

OPTION_BLOCK_RE = re.compile(r'^\s*[A-H]\s*[.．、:：。][\s]*\S')
OPTION_INLINE_RE = re.compile(r'(?:^|\s)[A-H]\s*[.．、:：。][\s]*\S')
QUESTION_NUM_RE = re.compile(r'^\s*(\d{1,3})\s*[.、．。]\s*\S')
QUESTION_PAREN_RE = re.compile(r'^\s*[（(]\s*(\d{1,3})\s*[）)]\s*\S')
QUESTION_TITLE_RE = re.compile(r'^\s*第\s*([一二三四五六七八九十百千\d]+)\s*题')
QUESTION_EXAMPLE_RE = re.compile(r'^\s*例\s*\d')
ANSWER_LEAD_RE = re.compile(r'^\s*(?:答案|参考答案|解析|分析|解答|【答案】|【解析】|【分析】|本题)')

# 章节标题（一/二/三级标题样式）
HEADING_NUMBERED_RE = re.compile(
    r'^\s*(?:'
    r'第\s*[一二三四五六七八九十百千万\d]+\s*[章节部篇]'
    r'|\d+\.\d+(?:\.\d+)?\s+\S'
    r'|第\s*\d+\s*[节章]'
    r')'
)

# 题干线索词
QUESTION_CUE_RE = re.compile(
    r'[?？]|下列|以下|关于|若|设|已知|正确|错误|不是|可以|能够|应|属于|采用|'
    r'给出|求|计算|证明|说明|分析|为什么|多少|哪个|哪些|如果|判断|选择|填空'
)

# 知识点线索词
KNOWLEDGE_CUE_RE = re.compile(
    r'是指|定义为|可以分为|包括|主要包括|具有.*特点|的特点是|指的是|'
    r'即|即为|被称为|通常|一般来说|首先|其次|最后|因此|所以'
)

# 噪声
NOISE_HEADER_FOOTER_RE = re.compile(
    r'^(?:第\s*\d+\s*页|page\s*\d+|—\s*\d+\s*—|·\s*\d+\s*·|目录|参考文献)$',
    re.IGNORECASE
)


# ===== 数据结构 =====


@dataclass
class BlockClassification:
    block_id: str
    block_index: int
    page_no: Optional[int]
    block_type: str  # 解析器原始类型
    text: str
    label: str  # 我们打的标签
    confidence: float  # 0~1
    signals: Dict[str, Any] = field(default_factory=dict)
    needs_llm: bool = False  # 是否需要 LLM 兜底


# ===== 分类器 =====


class BlockClassifier:
    """混排文档的 block 类型分类器"""

    LABELS = {
        "heading", "knowledge", "question_stem", "question_option",
        "answer", "table", "figure", "formula", "noise", "unknown",
    }

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client

    # ----- 第一遍：单块打分 -----

    def _classify_single(self, block: Any) -> BlockClassification:
        text = (getattr(block, "content_text", "") or getattr(block, "content_md", "") or "").strip()
        block_type = (getattr(block, "block_type", "") or "").lower()
        cls = BlockClassification(
            block_id=getattr(block, "id", ""),
            block_index=0,
            page_no=getattr(block, "page_no", None),
            block_type=block_type,
            text=text,
            label="unknown",
            confidence=0.0,
            signals={},
        )

        if not text and block_type not in ("figure", "table", "formula"):
            cls.label = "noise"
            cls.confidence = 0.9
            return cls

        # 资产类型直接打标
        if block_type == "table":
            cls.label = "table"
            cls.confidence = 1.0
            cls.signals["is_media_block"] = True
            return cls
        if block_type == "figure":
            cls.label = "figure"
            cls.confidence = 1.0
            cls.signals["is_media_block"] = True
            return cls
        if block_type == "formula":
            cls.label = "formula"
            cls.confidence = 1.0
            cls.signals["is_media_block"] = True
            return cls

        # 噪声
        if NOISE_HEADER_FOOTER_RE.match(text) or len(text) < 4:
            cls.label = "noise"
            cls.confidence = 0.85
            return cls

        # 标题样式
        if block_type in ("heading", "title") or HEADING_NUMBERED_RE.match(text):
            cls.label = "heading"
            cls.confidence = 0.9 if block_type in ("heading", "title") else 0.75
            return cls

        # 选项块
        if OPTION_BLOCK_RE.match(text):
            cls.label = "question_option"
            cls.confidence = 0.95
            cls.signals["has_option_marker"] = True
            return cls

        # 答案/解析块
        if ANSWER_LEAD_RE.match(text):
            cls.label = "answer"
            cls.confidence = 0.9
            return cls

        # 题干（题号 + 题号线索词）
        is_numbered = bool(QUESTION_NUM_RE.match(text) or QUESTION_PAREN_RE.match(text))
        is_question_title = bool(QUESTION_TITLE_RE.match(text) or QUESTION_EXAMPLE_RE.match(text))
        has_cue = bool(QUESTION_CUE_RE.search(text))
        has_inline_options = bool(OPTION_INLINE_RE.search(text)) and len(re.findall(r'(?:^|\s)[A-H]\s*[.．、]', text)) >= 3

        cls.signals.update({
            "is_numbered": is_numbered,
            "is_question_title": is_question_title,
            "has_question_cue": has_cue,
            "has_inline_options": has_inline_options,
            "text_length": len(text),
        })

        if is_question_title:
            cls.label = "question_stem"
            cls.confidence = 0.85
            return cls

        if is_numbered and (has_cue or has_inline_options or len(text) > 30):
            cls.label = "question_stem"
            cls.confidence = 0.85 if has_cue else 0.7
            return cls

        # 知识点 — 长段落、含定义线索、不像题目
        has_kn_cue = bool(KNOWLEDGE_CUE_RE.search(text))
        if len(text) >= 30 and not is_numbered and not has_inline_options:
            if has_kn_cue or block_type in ("paragraph", "list"):
                cls.label = "knowledge"
                cls.confidence = 0.7 if has_kn_cue else 0.55
                return cls

        # 其他模糊情况
        cls.label = "unknown"
        cls.confidence = 0.3
        cls.needs_llm = True
        return cls

    # ----- 第二遍：上下文修正 -----

    def _refine_with_context(self, classifications: List[BlockClassification]) -> None:
        n = len(classifications)
        for i, c in enumerate(classifications):
            prev = classifications[i - 1] if i > 0 else None
            next_c = classifications[i + 1] if i < n - 1 else None

            # 如果当前是 unknown 但前后都是题目相关块，归入题目
            if c.label == "unknown":
                neighbors = [x.label for x in (prev, next_c) if x]
                if "question_option" in neighbors or "question_stem" in neighbors:
                    if c.signals.get("text_length", 0) < 60 and OPTION_BLOCK_RE.match(c.text):
                        c.label = "question_option"
                    else:
                        c.label = "question_stem" if c.signals.get("text_length", 0) < 200 else "knowledge"
                        # 媒体块作为题干邻接内容时，也放回 figure，保障与题目块集合联动
                        if c.signals.get("is_media_block"):
                            c.label = "figure"
                    c.confidence = 0.55
                    c.needs_llm = False

            # 媒体块在题干后直接出现，避免被当作噪声后被排除
            if c.label == "figure" and prev is not None and prev.label == "question_stem":
                c.confidence = min(1.0, c.confidence + 0.2)

            # 答案块出现在选项块之后，确认是 answer
            if c.label == "answer" and prev and prev.label == "question_option":
                c.confidence = max(c.confidence, 0.95)

            # 题干后面紧跟一堆选项 → 提升题干置信度
            if c.label == "question_stem":
                option_count = 0
                for j in range(i + 1, min(i + 6, n)):
                    if classifications[j].label == "question_option":
                        option_count += 1
                    elif classifications[j].label != "noise":
                        break
                if option_count >= 2:
                    c.confidence = max(c.confidence, 0.95)

            # 标题之后紧跟段落 → 知识点
            if c.label == "unknown" and prev and prev.label in ("heading", "knowledge"):
                if c.signals.get("text_length", 0) >= 20 and not c.signals.get("is_numbered"):
                    c.label = "knowledge"
                    c.confidence = 0.6

            # 后续紧跟 knowledge 块也倾向知识点
            if c.label == "unknown" and next_c and next_c.label == "knowledge":
                if c.signals.get("text_length", 0) >= 20 and not c.signals.get("is_numbered"):
                    c.label = "knowledge"
                    c.confidence = 0.55

            # 整段全是噪声特征但长度小 → noise
            if c.label == "unknown" and len(c.text) < 15 and not c.signals.get("has_question_cue"):
                c.label = "noise"
                c.confidence = 0.5

    # ----- LLM 兜底 -----

    async def _llm_disambiguate(self, classifications: List[BlockClassification], window: int = 8) -> None:
        """对 needs_llm 的块批量送 LLM 判别（带窗口上下文）。"""
        if not self.llm_client or not getattr(self.llm_client, "is_available", False):
            return

        ambiguous_indices = [i for i, c in enumerate(classifications) if c.needs_llm and c.label in ("unknown",)]
        if not ambiguous_indices:
            return

        # 每次处理 5 个块以控制 prompt 长度
        for batch_start in range(0, len(ambiguous_indices), 5):
            batch = ambiguous_indices[batch_start: batch_start + 5]
            prompt = self._build_llm_prompt(classifications, batch, window)
            try:
                response = await self.llm_client.chat(prompt)
                self._apply_llm_response(classifications, batch, response)
            except Exception as e:
                logger.warning("Block 分类 LLM 兜底失败", error=str(e))
                continue

    def _build_llm_prompt(
        self, classifications: List[BlockClassification], target_indices: List[int], window: int
    ) -> str:
        lines = [
            "请对下列文档片段中标记为 [?] 的块进行分类，每个块从以下类型中选择一个：",
            "  - knowledge（知识点：概念、定义、解释、正文段落）",
            "  - question_stem（题干）",
            "  - question_option（选项块）",
            "  - answer（答案/解析）",
            "  - heading（章节标题）",
            "  - noise（页眉页脚或无意义内容）",
            "",
            "上下文（带 [?] 的是待分类块）：",
        ]
        target_set = set(target_indices)
        # 取 union(target ± window) 作为上下文
        context_indices = set()
        for i in target_indices:
            for j in range(max(0, i - window), min(len(classifications), i + window + 1)):
                context_indices.add(j)
        for j in sorted(context_indices):
            c = classifications[j]
            marker = "[?]" if j in target_set else f"[{c.label}]"
            text_excerpt = c.text[:200].replace("\n", " ")
            lines.append(f"#{j} {marker} {text_excerpt}")
        lines.append("")
        lines.append("请按 JSON 格式返回，键是块编号字符串，值是类型：")
        lines.append('{"5": "question_stem", "6": "question_option", ...}')
        return "\n".join(lines)

    def _apply_llm_response(
        self, classifications: List[BlockClassification], target_indices: List[int], response: str
    ) -> None:
        import json
        try:
            # 提取 JSON 段（容忍 LLM 多余内容）
            match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
            if not match:
                return
            payload = json.loads(match.group(0))
            for key, value in payload.items():
                idx = int(key)
                if idx in target_indices and value in self.LABELS:
                    classifications[idx].label = value
                    classifications[idx].confidence = 0.7
                    classifications[idx].needs_llm = False
                    classifications[idx].signals["llm_assigned"] = True
        except Exception as e:
            logger.warning("LLM 分类响应解析失败", error=str(e))

    # ----- 对外入口 -----

    async def classify(self, blocks: List[Any], use_llm: bool = False) -> List[BlockClassification]:
        results: List[BlockClassification] = []
        for idx, block in enumerate(blocks):
            cls = self._classify_single(block)
            cls.block_index = idx
            results.append(cls)

        self._refine_with_context(results)

        if use_llm:
            await self._llm_disambiguate(results)

        return results

    @staticmethod
    def stats(classifications: List[BlockClassification]) -> Dict[str, int]:
        return dict(Counter(c.label for c in classifications))
