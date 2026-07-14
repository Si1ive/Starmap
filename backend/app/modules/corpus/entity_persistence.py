"""Persistence helpers for entities produced by the corpus extraction pipeline."""

import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    EntitySourceLink,
    Question,
    QuestionChapterLink,
)
from app.modules.corpus.question_validation import (
    extract_question_number,
    get_option_label,
)
from app.services.chapter_compat_service import resolve_legacy_chapter_id

logger = get_logger(__name__)


def strip_leading_option_marker(
    text: str,
    expected_label: Optional[str] = None,
) -> str:
    """Remove duplicated or malformed markers from extracted option text."""
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
        cleaned = cleaned[malformed_sub.end():]
        cleaned = re.sub(r"^([^<]{0,60})</sub>", r"\1", cleaned, count=1).strip()
    return re.sub(r"^\s*[.．、:：。]\s*", "", cleaned).strip()


def normalize_options(
    options: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Normalize option keys while preserving their extraction provenance."""
    normalized: List[Dict[str, Any]] = []
    seen_labels = set()
    for option in options or []:
        label = get_option_label(option)
        text = str(option.get("text") or option.get("content") or "").strip()
        text = strip_leading_option_marker(text, expected_label=label)
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
    """Extract the lightweight topic terms used by the legacy pipeline."""
    terms = set()

    if title:
        clean_title = title.strip()
        for prefix in ["第", "章", "节", "、", "。", "：", ":", " "]:
            clean_title = clean_title.replace(prefix, " ")
        for word in clean_title.split():
            if len(word) >= 2:
                terms.add(word)

    if content:
        quoted = re.findall(r'[「「""]([^」」""]+)[」」""]', content)
        for quoted_term in quoted:
            if 2 <= len(quoted_term) <= 20:
                terms.add(quoted_term)

    return list(terms)[:20]


def extract_answers_from_blocks(blocks: List[Any]) -> Dict[str, str]:
    """Parse numbered answers from the answer section of a source document."""
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


class QuestionPersistence:
    """Persist extracted questions and reconnect answers to stored records."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def save_question(
        self,
        question_dict: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Persist one normalized question and its source relationships."""
        subject_id = question_dict.get("subject_id")
        legacy_chapter_id = question_dict.get("chapter_id")
        primary_chapter_id = question_dict.get("primary_chapter_id")

        if not legacy_chapter_id:
            legacy_chapter_id = await resolve_legacy_chapter_id(
                self.db,
                canonical_chapter_id=primary_chapter_id,
                subject_id=subject_id,
            )
            question_dict["chapter_id"] = legacy_chapter_id

        unassigned = not subject_id or not legacy_chapter_id
        if unassigned:
            logger.info(
                "题目归属缺失，以待指认状态入库",
                document_id=question_dict.get("document_id"),
                question_id=question_dict.get("id"),
                page_no=question_dict.get("page_no"),
                subject_id=subject_id,
                chapter_id=legacy_chapter_id,
            )

        try:
            async with self.db.begin_nested():
                options = normalize_options(question_dict.get("options"))
                question_content = (
                    question_dict.get("stem")
                    or question_dict.get("content")
                    or ""
                ).strip()
                tags = question_dict.get("tags") or None
                topic_terms = extract_topic_terms(
                    question_content,
                    question_content,
                ) or None

                question = Question(
                    id=question_dict["id"],
                    subject_id=subject_id,
                    chapter_id=legacy_chapter_id,
                    primary_chapter_id=primary_chapter_id,
                    source_document_id=question_dict["document_id"],
                    source_section_path=(
                        question_dict.get("source_section_path") or None
                    ),
                    type=question_dict["question_type"],
                    content=question_content,
                    options=options or None,
                    answer="",
                    source=question_dict.get("source") or None,
                    exam_year=int(question_dict.get("exam_year") or 0),
                    exam_scope=question_dict.get("exam_scope") or None,
                    paper_name=question_dict.get("paper_name") or None,
                    tags=tags,
                    topic_terms=topic_terms,
                    question_no=str(
                        extract_question_number(question_dict) or ""
                    ) or None,
                    review_status="pending",
                    status="active",
                    extraction_meta={
                        **(question_dict.get("extraction_meta") or {}),
                        "unassigned": unassigned,
                    },
                )
                self.db.add(question)

                if primary_chapter_id:
                    self.db.add(
                        QuestionChapterLink(
                            question_id=question_dict["id"],
                            canonical_chapter_id=primary_chapter_id,
                            is_primary=True,
                            source=question_dict.get("chapter_link_source") or "manual",
                            created_by="system",
                        )
                    )

                blocks = question_dict.get("blocks", [])
                if blocks:
                    self.db.add(
                        EntitySourceLink(
                            entity_type="question",
                            entity_id=question_dict["id"],
                            document_id=question_dict["document_id"],
                            page_start=blocks[0].page_no,
                            page_end=blocks[-1].page_no,
                            block_ids=question_dict.get("block_ids", []),
                            excerpt_text=question_dict["content"][:500],
                        )
                    )

                await self.db.flush()

                block_ids = question_dict.get("block_ids") or [
                    block.id for block in blocks
                ]
                if block_ids:
                    try:
                        from app.services.entity_asset_service import (
                            link_entity_assets_by_blocks,
                        )

                        await link_entity_assets_by_blocks(
                            self.db,
                            entity_type="question",
                            entity_id=question_dict["id"],
                            block_ids=block_ids,
                        )
                    except Exception as exc:
                        logger.warning(
                            "题目资产关联失败",
                            question_id=question_dict["id"],
                            error=str(exc),
                        )
            return True, "saved_unassigned" if unassigned else "saved"
        except Exception as exc:
            logger.error("保存题目失败", error=str(exc))
            return False, "save_failed"

    async def link_extracted_answers(
        self,
        document_id: str,
        blocks: List[Any],
    ) -> int:
        """Fill empty stored answers from a document's answer section."""
        rows = (
            await self.db.execute(
                select(Question).where(Question.source_document_id == document_id)
            )
        ).scalars().all()
        by_number = {
            str(question.question_no).strip(): question
            for question in rows
            if question.question_no
        }
        if not by_number:
            return 0

        extracted_answers = extract_answers_from_blocks(blocks)
        linked = 0
        for question_no, answer in extracted_answers.items():
            question = by_number.get(question_no)
            if not question or (question.answer or "").strip():
                continue
            question.answer = answer
            question.answer_source = "extracted"
            linked += 1

        if linked:
            await self.db.flush()
            logger.info(
                "PDF 答案区回连完成",
                document_id=document_id,
                linked=linked,
            )
        return linked

    async def get_source_links(
        self,
        entity_type: str,
        entity_id: str,
    ) -> List[Dict[str, Any]]:
        """Return source references for one extracted entity."""
        result = await self.db.execute(
            select(EntitySourceLink).where(
                and_(
                    EntitySourceLink.entity_type == entity_type,
                    EntitySourceLink.entity_id == entity_id,
                )
            )
        )
        links = result.scalars().all()
        return [
            {
                "id": link.id,
                "entity_type": link.entity_type,
                "entity_id": link.entity_id,
                "document_id": link.document_id,
                "page_start": link.page_start,
                "page_end": link.page_end,
                "block_ids": link.block_ids,
                "excerpt_text": link.excerpt_text,
                "created_at": link.created_at.isoformat() if link.created_at else None,
            }
            for link in links
        ]
