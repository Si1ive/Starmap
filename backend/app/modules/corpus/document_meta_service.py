"""
语料文档级元信息提取服务

从试卷/课本首页提取来源信息（年份、真题/模拟、辅导机构、试卷名），写回 Document，
并返回 doc_meta 供题目抽取阶段广播到每道题。

策略：规则优先（正则 + 机构词表）→ 规则未命中关键字段时用 LLM 兜底（doc_meta_llm）。
doc_meta_llm 未配置时纯规则降级，不报错。
"""

import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import Document, DocumentBlock
from app.services.llm_client import DocMetaLLMClient, extract_json_block
from app.modules.operations.settings_service import SystemSettingsService

logger = get_logger(__name__)

# 首页取多少个 block / 多少字符喂规则与 LLM
FIRST_PAGE_BLOCK_LIMIT = 40
FIRST_PAGE_CHAR_LIMIT = 4000

# 常见辅导机构 / 资料品牌词表（命中即作为来源机构）
INSTITUTION_KEYWORDS = [
    "王道", "天勤", "海天", "新东方", "文都", "启航", "高途", "考虫",
    "尚硅谷", "黑马", "汤家凤", "张宇", "李永乐", "徐涛",
]

# 真题 / 模拟题判定词
PAST_EXAM_WORDS = ["真题", "历年真题", "考研真题", "全国硕士研究生", "招生考试"]
MOCK_EXAM_WORDS = ["模拟", "押题", "预测", "冲刺卷", "模考"]

# 408 范围标识
EXAM_SCOPE_WORDS = ["408", "计算机学科专业基础综合", "计算机考研"]

_YEAR_RE = re.compile(r"(19|20)\d{2}")


def _detect_year(text: str) -> Optional[int]:
    """抓首个合理年份（1990-2099）。"""
    for m in _YEAR_RE.finditer(text):
        year = int(m.group(0))
        if 1990 <= year <= 2099:
            return year
    return None


def _detect_institution(text: str) -> Optional[str]:
    for kw in INSTITUTION_KEYWORDS:
        if kw in text:
            return kw
    # 通用「XX教育 / XX考研」模式
    m = re.search(r"([一-龥]{2,6})(教育|考研|辅导)", text)
    if m:
        return m.group(0)
    return None


def _detect_doc_kind(text: str, doc_type: str) -> str:
    """返回 past_exam / mock_exam / 沿用 doc_type。"""
    if any(w in text for w in PAST_EXAM_WORDS):
        return "past_exam"
    if any(w in text for w in MOCK_EXAM_WORDS):
        return "mock_exam"
    return doc_type


def _detect_exam_scope(text: str) -> Optional[str]:
    if "408" in text:
        return "408"
    if any(w in text for w in EXAM_SCOPE_WORDS):
        return "408"
    return None


_SOURCE_PROMPT = """下面是一份408考研资料（试卷或课本）首页的文本。请提取其来源元信息，只输出 JSON：
{{"exam_year": 2024 或 null, "doc_kind": "past_exam"|"mock_exam"|"textbook"|"other",
 "source_label": "如 2024年408真题 / 王道考研机构", "paper_name": "试卷名或书名，没有则 null",
 "institution": "辅导机构名，没有则 null", "exam_scope": "408 或 null"}}

要求：
1. exam_year 取最相关的年份（真题年份/出版年），没有就 null。
2. doc_kind：含"真题/历年/全国硕士研究生招生考试"判为 past_exam；含"模拟/押题/预测"判为 mock_exam；否则 textbook 或 other。
3. 只输出 JSON，不要解释。

首页文本：
---
{content}
---"""


class DocumentMetaService:
    """文档级元信息提取服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _first_page_text(self, document_id: str) -> str:
        """取文档首页（最小 page_no）的 block 文本拼接。"""
        rows = (await self.db.execute(
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
            .limit(200)
        )).scalars().all()
        if not rows:
            return ""
        min_page = rows[0].page_no
        first_page = [b for b in rows if b.page_no == min_page][:FIRST_PAGE_BLOCK_LIMIT]
        parts = [(b.content_text or b.content_md or "").strip() for b in first_page]
        text = "\n".join(p for p in parts if p)
        return text[:FIRST_PAGE_CHAR_LIMIT]

    async def _get_client(self) -> DocMetaLLMClient:
        runtime_settings = await SystemSettingsService(self.db).load()
        cfg = runtime_settings.get("doc_meta_llm", {})
        return DocMetaLLMClient(cfg if isinstance(cfg, dict) else {})

    def _apply_rules(self, text: str, doc_type: str) -> Dict[str, Any]:
        institution = _detect_institution(text)
        kind = _detect_doc_kind(text, doc_type)
        year = _detect_year(text)
        scope = _detect_exam_scope(text)
        # 试卷名/书名：取首页第一条较短的非空行作为候选
        paper_name = None
        for line in text.splitlines():
            line = line.strip()
            if 4 <= len(line) <= 40:
                paper_name = line
                break
        return {
            "exam_year": year,
            "doc_kind": kind,
            "institution": institution,
            "exam_scope": scope,
            "paper_name": paper_name,
        }

    @staticmethod
    def _compose_source_label(meta: Dict[str, Any], doc_type: str) -> str:
        """拼一个展示用来源串，如 '2024年408真题' / '王道考研'。"""
        parts: List[str] = []
        if meta.get("exam_year"):
            parts.append(f"{meta['exam_year']}年")
        if meta.get("exam_scope"):
            parts.append(str(meta["exam_scope"]))
        kind = meta.get("doc_kind") or doc_type
        kind_label = {"past_exam": "真题", "mock_exam": "模拟题", "textbook": "教材"}.get(kind, "")
        if kind_label:
            parts.append(kind_label)
        label = "".join(parts)
        if meta.get("institution"):
            label = f"{label}（{meta['institution']}）" if label else str(meta["institution"])
        return label or (meta.get("paper_name") or "")

    async def extract_and_store_meta(self, document_id: str) -> Dict[str, Any]:
        """提取并写回文档级元信息，返回 doc_meta dict。"""
        document = (await self.db.execute(
            select(Document).where(Document.id == document_id)
        )).scalar_one_or_none()
        if not document:
            raise ValueError(f"文档不存在: {document_id}")

        text = await self._first_page_text(document_id)
        doc_type = document.doc_type or "other"
        meta = self._apply_rules(text, doc_type)

        # 规则未命中关键字段（年份 + 机构都没有）时，LLM 兜底
        need_llm = not meta.get("exam_year") and not meta.get("institution")
        if need_llm and text:
            try:
                client = await self._get_client()
                if client.is_available:
                    raw = await client.chat(_SOURCE_PROMPT.format(content=text))
                    data = extract_json_block(raw)
                    if isinstance(data, dict):
                        for k in ("exam_year", "doc_kind", "institution", "exam_scope", "paper_name"):
                            if not meta.get(k) and data.get(k):
                                meta[k] = data[k]
                        if data.get("source_label"):
                            meta["source_label"] = data["source_label"]
            except Exception as e:
                logger.warning("doc_meta LLM 兜底失败，使用规则结果", document_id=document_id, error=str(e))

        if not meta.get("source_label"):
            meta["source_label"] = self._compose_source_label(meta, doc_type)

        # 写回 Document（已有字段，无需迁移）
        if meta.get("source_label"):
            document.source_label = str(meta["source_label"])[:255]
        if meta.get("exam_year"):
            try:
                document.exam_year = int(meta["exam_year"])
            except (TypeError, ValueError):
                pass
        if meta.get("exam_scope"):
            document.exam_scope = str(meta["exam_scope"])[:50]
        if meta.get("paper_name"):
            document.paper_name = str(meta["paper_name"])[:255]
        await self.db.flush()

        logger.info("文档元信息提取完成", document_id=document_id,
                    source_label=document.source_label, exam_year=document.exam_year)
        return {
            "source_label": document.source_label,
            "exam_year": document.exam_year,
            "exam_scope": document.exam_scope,
            "paper_name": document.paper_name,
            "doc_kind": meta.get("doc_kind") or doc_type,
            "institution": meta.get("institution"),
        }
