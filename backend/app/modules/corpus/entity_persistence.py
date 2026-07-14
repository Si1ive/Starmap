"""Persistence helpers for entities produced by the corpus extraction pipeline."""

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    EntitySourceLink,
    KnowledgePoint,
    KnowledgePointChapterLink,
    Question,
    QuestionChapterLink,
)
from app.modules.corpus.question_validation import (
    extract_question_number,
    get_option_label,
)
from app.services.chapter_compat_service import resolve_legacy_chapter_id

logger = get_logger(__name__)


def generate_id() -> str:
    """Generate the compact identifiers used by extracted entities."""
    return uuid.uuid4().hex[:32]


async def cleanup_document_entities(
    db: AsyncSession,
    document_id: str,
    entity_type: Optional[str] = None,
) -> Dict[str, int]:
    """Delete extracted entities and their external index relationships."""
    entity_types = (
        ["knowledge_point", "question"]
        if entity_type is None
        else [entity_type]
    )
    removed: Dict[str, int] = {}
    for current_type in entity_types:
        model = KnowledgePoint if current_type == "knowledge_point" else Question
        rows = await db.execute(
            select(model.id).where(model.source_document_id == document_id)
        )
        entity_ids = [row[0] for row in rows.all()]
        removed[current_type] = len(entity_ids)
        if not entity_ids:
            continue

        await db.execute(
            delete(EntitySourceLink).where(
                and_(
                    EntitySourceLink.entity_type == current_type,
                    EntitySourceLink.entity_id.in_(entity_ids),
                )
            )
        )
        try:
            from app.services.entity_asset_service import cleanup_entity_links

            await cleanup_entity_links(
                db,
                entity_type=current_type,
                entity_ids=entity_ids,
            )
        except Exception:
            pass

        from app.modules.retrieval.segment_service import SegmentService

        await SegmentService(db).delete_entity_segments(
            current_type,
            entity_ids,
        )
        await db.execute(delete(model).where(model.id.in_(entity_ids)))
    return removed


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


def build_knowledge_content(content_blocks: List[Any]) -> str:
    """Join non-empty knowledge point blocks using Markdown paragraph spacing."""
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


class KnowledgePointPersistence:
    """Persist extracted knowledge points and their source relationships."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def save_knowledge_point(
        self,
        document_id: str,
        fallback_subject_id: str,
        title_block: Any,
        content_blocks: List[Any],
        mapping_info: Optional[Dict[str, Optional[str]]],
    ) -> bool:
        """Persist one knowledge point using an already resolved page mapping."""
        primary_chapter_id = mapping_info["chapter_id"] if mapping_info else None
        subject_id = (
            mapping_info["subject_id"] if mapping_info else fallback_subject_id
        )
        legacy_chapter_id = (
            mapping_info["legacy_chapter_id"] if mapping_info else None
        )
        source_section_path = (
            mapping_info.get("source_section_path") if mapping_info else None
        )
        resolved_source: Optional[str] = None

        content = build_knowledge_content(content_blocks)
        if not content:
            return False

        title_text = getattr(title_block, "content_text", None) or ""
        if not primary_chapter_id:
            from app.modules.catalog.chapter_link_service import ChapterLinkService

            resolved = await ChapterLinkService(
                self.db
            ).resolve_chapter_for_entity(
                title=title_text,
                content=content[:1000],
                subject_id=subject_id,
                topic_terms=extract_topic_terms(title_text, content),
                entity_type="knowledge_point",
            )
            if resolved:
                primary_chapter_id = resolved["chapter_id"]
                subject_id = resolved.get("subject_id") or subject_id
                resolved_source = resolved.get("source", "keyword_match")
                logger.info(
                    "知识点章节直接解析成功",
                    document_id=document_id,
                    chapter_id=primary_chapter_id,
                    source=resolved_source,
                    confidence=resolved.get("confidence"),
                )

        if not legacy_chapter_id:
            legacy_chapter_id = await resolve_legacy_chapter_id(
                self.db,
                canonical_chapter_id=primary_chapter_id,
                subject_id=subject_id,
            )
        if not subject_id or not legacy_chapter_id:
            logger.warning(
                "知识点缺少有效章节归属，跳过入库",
                document_id=document_id,
                block_id=getattr(title_block, "id", None),
            )
            return False

        knowledge_point_id = generate_id()
        self.db.add(
            KnowledgePoint(
                id=knowledge_point_id,
                chapter_id=legacy_chapter_id,
                subject_id=subject_id,
                primary_chapter_id=primary_chapter_id,
                source_document_id=document_id,
                source_section_path=source_section_path,
                title=title_text or "未命名知识点",
                canonical_title=title_text,
                content=content,
                topic_terms=extract_topic_terms(title_text, content),
                review_status="pending",
                status="active",
            )
        )

        if primary_chapter_id:
            self.db.add(
                KnowledgePointChapterLink(
                    knowledge_point_id=knowledge_point_id,
                    canonical_chapter_id=primary_chapter_id,
                    is_primary=True,
                    source=resolved_source
                    or ("document_mapping" if mapping_info else "manual"),
                    created_by="system",
                )
            )

        block_ids = [title_block.id] + [block.id for block in content_blocks]
        self.db.add(
            EntitySourceLink(
                entity_type="knowledge_point",
                entity_id=knowledge_point_id,
                document_id=document_id,
                page_start=title_block.page_no,
                page_end=(
                    content_blocks[-1].page_no
                    if content_blocks
                    else title_block.page_no
                ),
                block_ids=block_ids,
                excerpt_text=content[:500] if content else None,
            )
        )
        await self.db.flush()

        try:
            from app.services.entity_asset_service import (
                link_entity_assets_by_blocks,
            )

            await link_entity_assets_by_blocks(
                self.db,
                entity_type="knowledge_point",
                entity_id=knowledge_point_id,
                block_ids=block_ids,
            )
        except Exception as exc:
            logger.warning(
                "知识点资产关联失败",
                knowledge_point_id=knowledge_point_id,
                error=str(exc),
            )
        return True


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
