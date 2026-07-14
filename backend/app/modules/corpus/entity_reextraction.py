"""Targeted re-extraction for one persisted question or knowledge point."""

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    Document,
    DocumentBlock,
    EntitySourceLink,
    KnowledgePoint,
    Question,
)
from app.modules.corpus.document_mapping import DocumentChapterMappingResolver
from app.modules.corpus.entity_extraction_pipeline import clean_document_blocks
from app.modules.corpus.entity_persistence import (
    KnowledgePointPersistence,
    QuestionPersistence,
)
from app.modules.corpus.errors import (
    EntityNotFoundError,
    EntitySourceUnavailableError,
)
from app.modules.corpus.question_pipeline import QuestionExtractionPipeline


class EntityReextractionService:
    """Rebuild one entity from its traceable source blocks."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        question_pipeline: Optional[QuestionExtractionPipeline] = None,
        question_persistence: Optional[QuestionPersistence] = None,
        knowledge_persistence: Optional[KnowledgePointPersistence] = None,
        chapter_mapping: Optional[DocumentChapterMappingResolver] = None,
    ):
        self.db = db
        self.question_pipeline = (
            question_pipeline or QuestionExtractionPipeline(db)
        )
        self.question_persistence = (
            question_persistence or QuestionPersistence(db)
        )
        self.knowledge_persistence = (
            knowledge_persistence or KnowledgePointPersistence(db)
        )
        self.chapter_mapping = (
            chapter_mapping or DocumentChapterMappingResolver(db)
        )

    async def reextract(
        self,
        *,
        document_id: str,
        entity_type: str,
        entity_id: str,
    ) -> Dict[str, Any]:
        """Re-extract and replace one target while preserving its stable ID."""
        document = await self.db.get(Document, document_id)
        if not document:
            raise EntityNotFoundError("文档不存在")

        if entity_type == "question":
            result = await self._reextract_question(
                document,
                entity_id,
            )
        elif entity_type == "knowledge_point":
            result = await self._reextract_knowledge_point(
                document,
                entity_id,
            )
        else:
            raise ValueError(f"不支持的实体类型: {entity_type}")

        await self.db.commit()
        return result

    async def _reextract_question(
        self,
        document: Document,
        entity_id: str,
    ) -> Dict[str, Any]:
        question = await self._load_entity(
            Question,
            entity_id,
            document.id,
        )
        target_source, context_sources = (
            await self._load_question_context_sources(
                document.id,
                question,
            )
        )
        target_block_ids = set(target_source.block_ids or [])
        blocks = await self._load_blocks(
            document.id,
            self._unique_block_ids(context_sources),
        )
        if not target_block_ids.intersection(
            {block.id for block in blocks}
        ):
            raise EntitySourceUnavailableError(
                "目标题目的来源 block 已不存在，无法单独重新提取"
            )

        section_mappings = await self.chapter_mapping.load(document.id)
        prepared = await self.question_pipeline.prepare_questions(
            document_id=document.id,
            fallback_subject_id=(
                question.subject_id or document.subject_id or ""
            ),
            blocks=clean_document_blocks(blocks),
            section_mappings=section_mappings,
            doc_meta={
                "exam_year": question.exam_year or None,
                "source_label": question.source,
                "paper_name": question.paper_name,
                "exam_scope": question.exam_scope,
            },
            doc_type=document.doc_type or "other",
        )
        candidate = self.select_question_candidate(
            prepared.get("questions") or [],
            target_question_no=question.question_no,
            target_block_ids=target_block_ids,
        )
        if not candidate:
            raise EntitySourceUnavailableError(
                "来源上下文未能重新识别出目标题目"
            )

        candidate = dict(candidate)
        candidate["id"] = question.id
        candidate["document_id"] = document.id
        await self.question_persistence.replace_question(
            question,
            candidate,
        )
        return {
            "document_id": document.id,
            "entity_type": "question",
            "entity_id": question.id,
            "question_no": question.question_no,
            "question_type": question.type,
            "knowledge_count": 0,
            "question_count": 1,
            "source_block_ids": candidate.get("block_ids") or [],
            "diagnostic": {
                "initial_report": prepared.get("initial_report") or {},
                "after_rule_fix": prepared.get("after_rule_fix") or {},
                "final_report": prepared.get("final_report") or {},
            },
        }

    async def _reextract_knowledge_point(
        self,
        document: Document,
        entity_id: str,
    ) -> Dict[str, Any]:
        knowledge_point = await self._load_entity(
            KnowledgePoint,
            entity_id,
            document.id,
        )
        source = await self._load_source_link(
            "knowledge_point",
            entity_id,
            document.id,
        )
        source_ids = list(source.block_ids or [])
        blocks = await self._load_blocks(document.id, source_ids)
        block_by_id = {block.id: block for block in blocks}
        ordered_blocks = [
            block_by_id[block_id]
            for block_id in source_ids
            if block_id in block_by_id
        ]
        if len(ordered_blocks) < 2:
            raise EntitySourceUnavailableError(
                "知识点来源 block 不完整，无法单独重新提取"
            )

        title_block = ordered_blocks[0]
        content_blocks = ordered_blocks[1:]
        replaced = await self.knowledge_persistence.replace_knowledge_point(
            knowledge_point,
            title_block=title_block,
            content_blocks=content_blocks,
        )
        if not replaced:
            raise EntitySourceUnavailableError(
                "知识点来源中没有可重新提取的正文"
            )
        return {
            "document_id": document.id,
            "entity_type": "knowledge_point",
            "entity_id": knowledge_point.id,
            "knowledge_count": 1,
            "question_count": 0,
            "source_block_ids": source_ids,
        }

    async def _load_entity(
        self,
        model: Any,
        entity_id: str,
        document_id: str,
    ) -> Any:
        entity = await self.db.get(model, entity_id)
        if (
            not entity
            or entity.source_document_id != document_id
            or entity.status == "deleted"
        ):
            raise EntityNotFoundError("目标实体不存在或不属于当前文档")
        return entity

    async def _load_source_link(
        self,
        entity_type: str,
        entity_id: str,
        document_id: str,
    ) -> EntitySourceLink:
        source = (
            await self.db.execute(
                select(EntitySourceLink)
                .where(
                    EntitySourceLink.entity_type == entity_type,
                    EntitySourceLink.entity_id == entity_id,
                    EntitySourceLink.document_id == document_id,
                )
                .order_by(EntitySourceLink.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not source or not source.block_ids:
            raise EntitySourceUnavailableError(
                "目标实体没有可追溯的来源 block"
            )
        return source

    async def _load_question_context_sources(
        self,
        document_id: str,
        target: Question,
    ) -> Tuple[EntitySourceLink, List[EntitySourceLink]]:
        target_source = await self._load_source_link(
            "question",
            target.id,
            document_id,
        )
        links = (
            await self.db.execute(
                select(EntitySourceLink)
                .where(
                    EntitySourceLink.entity_type == "question",
                    EntitySourceLink.document_id == document_id,
                )
                .order_by(EntitySourceLink.created_at.desc())
            )
        ).scalars().all()
        latest_link_by_entity: Dict[str, EntitySourceLink] = {}
        for link in links:
            latest_link_by_entity.setdefault(link.entity_id, link)
        latest_link_by_entity[target.id] = target_source

        questions = (
            await self.db.execute(
                select(Question).where(
                    Question.id.in_(list(latest_link_by_entity)),
                    Question.source_document_id == document_id,
                    Question.status != "deleted",
                )
            )
        ).scalars().all()
        questions = sorted(
            questions,
            key=lambda item: self._question_source_sort_key(
                item,
                latest_link_by_entity[item.id],
            ),
        )
        target_index = next(
            (
                index
                for index, item in enumerate(questions)
                if item.id == target.id
            ),
            None,
        )
        if target_index is None:
            return target_source, [target_source]

        context_questions = questions[
            max(0, target_index - 1):target_index + 2
        ]
        return target_source, [
            latest_link_by_entity[item.id]
            for item in context_questions
            if latest_link_by_entity[item.id].block_ids
        ]

    async def _load_blocks(
        self,
        document_id: str,
        block_ids: Sequence[str],
    ) -> List[DocumentBlock]:
        ids = [block_id for block_id in block_ids if block_id]
        if not ids:
            raise EntitySourceUnavailableError(
                "目标实体没有可读取的来源 block"
            )
        return (
            await self.db.execute(
                select(DocumentBlock)
                .where(
                    DocumentBlock.document_id == document_id,
                    DocumentBlock.id.in_(ids),
                )
                .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
            )
        ).scalars().all()

    @staticmethod
    def _unique_block_ids(
        sources: Iterable[EntitySourceLink],
    ) -> List[str]:
        unique: List[str] = []
        seen: Set[str] = set()
        for source in sources:
            for block_id in source.block_ids or []:
                if block_id and block_id not in seen:
                    seen.add(block_id)
                    unique.append(block_id)
        return unique

    @classmethod
    def select_question_candidate(
        cls,
        candidates: Sequence[Dict[str, Any]],
        *,
        target_question_no: Optional[str],
        target_block_ids: Set[str],
    ) -> Optional[Dict[str, Any]]:
        """Prefer the same question number, then the strongest source overlap."""
        if not candidates:
            return None
        normalized_target_no = cls._normalize_question_no(
            target_question_no
        )

        def score(candidate: Dict[str, Any]) -> Tuple[int, int, int]:
            candidate_blocks = set(candidate.get("block_ids") or [])
            overlap = len(target_block_ids.intersection(candidate_blocks))
            number_match = int(
                bool(normalized_target_no)
                and cls._normalize_question_no(
                    candidate.get("question_no")
                )
                == normalized_target_no
            )
            return (
                number_match,
                overlap,
                -len(candidate_blocks - target_block_ids),
            )

        selected = max(candidates, key=score)
        if score(selected)[1] == 0:
            return None
        return selected

    @staticmethod
    def _normalize_question_no(value: Any) -> Optional[str]:
        match = re.search(r"\d+", str(value or ""))
        return str(int(match.group())) if match else None

    @classmethod
    def _question_source_sort_key(
        cls,
        question: Question,
        source: EntitySourceLink,
    ) -> Tuple[int, int, str]:
        normalized_no = cls._normalize_question_no(question.question_no)
        return (
            int(source.page_start or 10**9),
            int(normalized_no) if normalized_no else 10**9,
            question.id,
        )
