"""Build normalized question dictionaries from grouped document blocks."""

import json
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.corpus.document_mapping import (
    DocumentChapterMappingResolver,
    PageMappingIndex,
)
from app.modules.corpus.entity_persistence import generate_id
from app.modules.corpus.question_layout import (
    QuestionGroup,
    QuestionLayoutGrouper,
)
from app.modules.corpus.question_type import infer_question_type
from app.services.chapter_compat_service import resolve_legacy_chapter_id

logger = get_logger(__name__)


STEM_YEAR_RE = re.compile(
    r"[\[【(（]?\s*((?:19|20)\d{2})\s*(?:年)?\s*[\]】)）]?"
)


def detect_stem_year(text: str) -> Optional[int]:
    """Detect an exam year near the start of a question stem."""
    match = STEM_YEAR_RE.search((text or "")[:30])
    if not match:
        return None
    year = int(match.group(1))
    return year if 1990 <= year <= 2099 else None


def build_question_tags(
    question_type: str,
    exam_year: Optional[int],
    is_real: bool,
) -> List[str]:
    """Build structured type, source, and year tags."""
    type_label = {
        "choice": "选择题",
        "fill": "填空题",
        "judge": "判断题",
        "short_answer": "简答题",
        "design": "设计题",
        "analysis": "分析题",
    }.get(question_type, "")
    tags: List[str] = []
    if type_label:
        tags.append(type_label)
    tags.append("真题" if is_real else "课后习题")
    if exam_year:
        tags.append(str(exam_year))
    return tags


def detect_merged_question_nos(
    text: str,
    base_no: Optional[int],
) -> List[int]:
    """Detect up to three successor question numbers embedded in one group."""
    if base_no is None or not text:
        return []
    found: List[int] = []
    for match in re.finditer(
        r"(?<!\d)(\d{1,3})\s*[.、．。]\s*(?=\S)",
        text,
    ):
        number = int(match.group(1))
        if base_no < number <= base_no + 3 and number not in found:
            found.append(number)
    return found


async def split_merged_questions(
    llm_client: Any,
    raw_text: str,
    base_no: int,
    successor_nos: List[int],
) -> Optional[List[Dict[str, Any]]]:
    """Ask the structure LLM to split text without adding new content."""
    question_numbers = ", ".join(
        str(number) for number in [base_no, *successor_nos]
    )
    prompt = f"""下面这段文本是从试卷 PDF 中提取的，疑似把多道题（题号 {question_numbers}）粘连在了一起。
请按题号把它们切分成独立题目。严格要求：
1. 只做切分，不要补全、改写、编造任何内容——所有文字都必须来自原文。
2. 每道题输出题号、题干、选项（如果是选择题）。选项格式 {{"key":"A","text":"..."}}。
3. 若某题没有选项（简答/大题），options 为空数组。

原始文本：
{raw_text}

只输出 JSON 数组，格式：
[{{"question_no": {base_no}, "stem": "...", "options": [{{"key":"A","text":"..."}}]}}, ...]"""
    try:
        response = await llm_client.chat(prompt, purpose="题目粘连切分")
        start = response.find("[")
        end = response.rfind("]")
        if start < 0 or end <= start:
            logger.warning(
                "LLM 切分返回无有效 JSON 数组",
                base_no=base_no,
            )
            return None
        parsed = json.loads(response[start:end + 1])
        if not isinstance(parsed, list) or len(parsed) < 2:
            return None

        questions: List[Dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict) or not (
                item.get("stem") or ""
            ).strip():
                continue
            options = []
            for option in item.get("options") or []:
                if not isinstance(option, dict) or not option.get("text"):
                    continue
                key = str(
                    option.get("key") or option.get("label") or ""
                ).strip().upper()[:1]
                options.append(
                    {
                        "key": key,
                        "label": key,
                        "option_label": key,
                        "text": option["text"].strip(),
                    }
                )
            questions.append(
                {
                    "question_no": item.get("question_no"),
                    "stem": item["stem"].strip(),
                    "options": options,
                }
            )
        return questions if len(questions) >= 2 else None
    except Exception as exc:
        logger.warning(
            "LLM 切分失败，保留原组",
            base_no=base_no,
            error=str(exc),
        )
        return None


def build_extraction_meta(
    blocks: List[Any],
    options: List[Dict[str, str]],
    question_type: str,
    question_no: Optional[str],
    has_figures: bool,
    group_label_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build extraction-quality metadata for one question."""
    block_count = len(blocks)
    option_count = len(options)
    suspected_truncated = False
    if question_type == "choice" and options:
        suspected_truncated = any(
            len((option.get("text") or "").strip()) < 2
            for option in options
        )
    return {
        "group_source": "single_block" if block_count == 1 else "merged",
        "block_count": block_count,
        "option_count": option_count,
        "has_figures": has_figures,
        "missing_question_no": not question_no,
        "suspected_truncated_options": suspected_truncated,
        "few_options": (
            question_type == "choice" and 0 < option_count < 4
        ),
        "group_label_reason": group_label_reason,
    }


class QuestionBuilder:
    """Convert grouped blocks or split results into persistence dictionaries."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_split_question(
        self,
        base: Dict[str, Any],
        part: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build one traceable question from an LLM split result."""
        question = dict(base)
        stem = part.get("stem") or ""
        options = part.get("options") or []
        question_no = part.get("question_no")
        question_type = infer_question_type(stem, options)
        if question_type != "choice":
            options = []

        question["id"] = generate_id()
        question["stem"] = stem
        question["content"] = stem
        question["raw_text"] = stem
        question["options"] = options
        question["question_no"] = (
            str(question_no) if question_no is not None else None
        )
        question["question_type"] = question_type
        question["type"] = question_type

        primary_chapter_id = base.get("primary_chapter_id")
        subject_id = base.get("subject_id")
        resolved_source = base.get("chapter_link_source")
        try:
            from app.modules.catalog.chapter_link_service import ChapterLinkService

            resolved = await ChapterLinkService(
                self.db
            ).resolve_chapter_for_entity(
                title=stem[:200],
                content=stem,
                subject_id=subject_id,
                entity_type="question",
                options=options,
            )
            if resolved:
                primary_chapter_id = resolved["chapter_id"]
                subject_id = resolved["subject_id"] or subject_id
                resolved_source = resolved.get("source", "vector_search")
        except Exception as exc:
            logger.warning(
                "切分题章节解析失败，沿用原组归属",
                error=str(exc),
            )
        question["primary_chapter_id"] = primary_chapter_id
        question["subject_id"] = subject_id
        question["chapter_link_source"] = resolved_source

        metadata = dict(base.get("extraction_meta") or {})
        metadata["fixed_by_llm"] = "split"
        metadata["option_count"] = len(options)
        metadata["few_options"] = (
            question_type == "choice" and 0 < len(options) < 4
        )
        question["extraction_meta"] = metadata
        return question

    async def group_to_dict(
        self,
        document_id: str,
        fallback_subject_id: str,
        group: QuestionGroup,
        section_mappings: PageMappingIndex,
        grouper: QuestionLayoutGrouper,
        doc_meta: Optional[Dict[str, Any]] = None,
        doc_type: str = "other",
    ) -> Optional[Dict[str, Any]]:
        """Convert a classified layout group into a normalized question."""
        blocks = group.blocks
        if not blocks:
            return None

        first_block = blocks[0]
        mapping_info = DocumentChapterMappingResolver.resolve(
            getattr(first_block, "page_no", None),
            section_mappings,
        )
        primary_chapter_id = (
            mapping_info["chapter_id"] if mapping_info else None
        )
        subject_id = (
            mapping_info["subject_id"]
            if mapping_info
            else fallback_subject_id
        )
        legacy_chapter_id = (
            mapping_info["legacy_chapter_id"] if mapping_info else None
        )
        source_section_path = (
            mapping_info.get("source_section_path") if mapping_info else None
        )
        resolved_source: Optional[str] = None

        stem = grouper._extract_stem(group)
        options = grouper._extract_options(group)
        figures = grouper._extract_figures(group)
        question_no = grouper._extract_question_no(group)
        group_label, group_label_reason = grouper.classify_group(
            group,
            options,
            question_no,
        )
        if group_label != "question":
            return None

        content = "\n".join(
            text.strip()
            for block in blocks
            if (
                text := (
                    getattr(block, "content_md", None)
                    or getattr(block, "content_text", None)
                    or ""
                )
            ).strip()
        )
        if not content:
            return None

        question_type = infer_question_type(content, options)
        if question_type != "choice":
            options = []
            stem = content

        if not primary_chapter_id:
            from app.modules.catalog.chapter_link_service import ChapterLinkService

            try:
                resolved = await ChapterLinkService(
                    self.db
                ).resolve_chapter_for_entity(
                    title=stem[:200],
                    content=content,
                    subject_id=subject_id,
                    entity_type="question",
                    options=options,
                )
                if resolved:
                    primary_chapter_id = resolved["chapter_id"]
                    subject_id = resolved["subject_id"] or subject_id
                    resolved_source = resolved.get(
                        "source",
                        "vector_search",
                    )
                    logger.info(
                        "题目章节解析（bbox v2）",
                        chapter_id=primary_chapter_id,
                        confidence=resolved.get("confidence"),
                        source=resolved.get("source"),
                    )
            except Exception as exc:
                logger.warning(
                    "题目章节解析失败，跳过",
                    error=str(exc),
                )

        if not legacy_chapter_id:
            legacy_chapter_id = await resolve_legacy_chapter_id(
                self.db,
                canonical_chapter_id=primary_chapter_id,
                subject_id=subject_id,
            )

        doc_meta = doc_meta or {}
        stem_year = detect_stem_year(content)
        if stem_year:
            exam_year = stem_year
            source = f"{stem_year}年真题"
            paper_name = doc_meta.get("source_label") or None
        elif doc_meta.get("exam_year"):
            exam_year = doc_meta.get("exam_year")
            source = doc_meta.get("source_label") or None
            paper_name = (
                doc_meta.get("paper_name")
                or doc_meta.get("source_label")
                or None
            )
        else:
            exam_year = 0
            institution = doc_meta.get("institution")
            if doc_type == "textbook":
                source = (
                    f"课后习题（{institution}）"
                    if institution
                    else "课后习题"
                )
            else:
                source = (
                    doc_meta.get("source_label")
                    or institution
                    or None
                )
            paper_name = (
                doc_meta.get("paper_name")
                or doc_meta.get("source_label")
                or None
            )

        return {
            "id": generate_id(),
            "document_id": document_id,
            "source_section_path": source_section_path,
            "subject_id": subject_id,
            "chapter_id": legacy_chapter_id,
            "primary_chapter_id": primary_chapter_id,
            "chapter_link_source": resolved_source
            or ("document_mapping" if mapping_info else None),
            "question_type": question_type,
            "type": question_type,
            "content": stem if options else content,
            "stem": stem if options else content,
            "options": options,
            "page_no": getattr(first_block, "page_no", None),
            "block_ids": [
                block.id
                for block in blocks
                if getattr(block, "id", None)
            ],
            "blocks": blocks,
            "raw_text": content,
            "source": source,
            "exam_year": int(exam_year or 0),
            "exam_scope": doc_meta.get("exam_scope"),
            "paper_name": paper_name,
            "tags": build_question_tags(
                question_type,
                exam_year,
                bool(stem_year),
            ),
            "question_no": question_no,
            "figures": figures,
            "extraction_meta": build_extraction_meta(
                blocks=blocks,
                options=options,
                question_type=question_type,
                question_no=question_no,
                has_figures=bool(figures),
                group_label_reason=group_label_reason,
            ),
        }
