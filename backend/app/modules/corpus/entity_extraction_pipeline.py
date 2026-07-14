"""Document-level orchestration for corpus entity extraction."""

from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import Document, DocumentBlock
from app.modules.corpus.document_mapping import (
    DocumentChapterMappingResolver,
    PageMappingIndex,
)
from app.modules.corpus.entity_persistence import (
    QuestionPersistence,
    cleanup_document_entities,
)
from app.modules.corpus.knowledge_pipeline import KnowledgeExtractionPipeline
from app.modules.corpus.question_pipeline import QuestionExtractionPipeline
from app.services.block_classifier import BlockClassifier
from app.services.document_meta_service import DocumentMetaService
from app.services.text_cleaning import clean_block_text

logger = get_logger(__name__)

KNOWLEDGE_BLOCK_LABELS = {
    "knowledge",
    "heading",
    "table",
    "figure",
    "formula",
}


def clean_document_blocks(blocks: Iterable[Any]) -> List[Any]:
    """Clean text fields shared by question and knowledge extraction."""
    cleaned_blocks = list(blocks)
    for block in cleaned_blocks:
        if getattr(block, "content_text", None):
            block.content_text = clean_block_text(block.content_text)
        if getattr(block, "content_md", None):
            block.content_md = clean_block_text(block.content_md)
    return cleaned_blocks


def select_knowledge_blocks(
    blocks: Iterable[Any],
    consumed_block_ids: Set[str],
    block_label_by_id: Dict[str, str],
) -> List[Any]:
    """Select classified knowledge blocks, falling back to all unconsumed."""
    remaining = [
        block
        for block in blocks
        if getattr(block, "id", None) not in consumed_block_ids
    ]
    classified = [
        block
        for block in remaining
        if block_label_by_id.get(
            getattr(block, "id", ""),
            "",
        )
        in KNOWLEDGE_BLOCK_LABELS
    ]
    return classified or remaining


def find_uncovered_pages(
    blocks: Iterable[Any],
    section_mappings: PageMappingIndex,
) -> List[int]:
    """Return document pages that have no direct section mapping."""
    all_pages = sorted(
        {
            block.page_no
            for block in blocks
            if getattr(block, "page_no", None) is not None
        }
    )
    covered_pages = set(section_mappings)
    return [page for page in all_pages if page not in covered_pages]


class DocumentEntityExtractionPipeline:
    """Coordinate classification, extraction, persistence, and diagnostics."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        chapter_mapping: Optional[DocumentChapterMappingResolver] = None,
        knowledge_pipeline: Optional[KnowledgeExtractionPipeline] = None,
        question_pipeline: Optional[QuestionExtractionPipeline] = None,
        question_persistence: Optional[QuestionPersistence] = None,
    ):
        self.db = db
        self.chapter_mapping = (
            chapter_mapping or DocumentChapterMappingResolver(db)
        )
        self.knowledge_pipeline = (
            knowledge_pipeline or KnowledgeExtractionPipeline(db)
        )
        self.question_pipeline = (
            question_pipeline or QuestionExtractionPipeline(db)
        )
        self.question_persistence = (
            question_persistence or QuestionPersistence(db)
        )
        self.last_document_type = "other"

    async def extract(
        self,
        document_id: str,
        extract_knowledge: bool = True,
        extract_questions: bool = True,
        fallback_subject_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract enabled entity types from one parsed document."""
        document = (
            await self.db.execute(
                select(Document).where(Document.id == document_id)
            )
        ).scalar_one_or_none()
        if not document:
            raise ValueError(f"文档不存在: {document_id}")

        fallback_subject_id = fallback_subject_id or document.subject_id
        try:
            doc_meta = await DocumentMetaService(
                self.db
            ).extract_and_store_meta(document_id)
        except Exception as exc:
            logger.warning(
                "文档元信息提取失败，题目来源将留空",
                document_id=document_id,
                error=str(exc),
            )
            doc_meta = {}
        self.last_document_type = document.doc_type or "other"

        blocks = (
            await self.db.execute(
                select(DocumentBlock)
                .where(DocumentBlock.document_id == document_id)
                .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
            )
        ).scalars().all()
        if not blocks:
            return {
                "knowledge_count": 0,
                "question_count": 0,
                "question_diagnostic": None,
                "message": "文档没有 blocks",
            }

        blocks = clean_document_blocks(blocks)
        classifier_llm = await self.question_pipeline.get_llm_client()
        classifier = BlockClassifier(llm_client=classifier_llm)
        classifications = await classifier.classify(
            blocks,
            use_llm=bool(
                classifier_llm and classifier_llm.is_available
            ),
        )
        block_label_by_id = {
            classification.block_id: classification.label
            for classification in classifications
            if classification.block_id
        }
        classification_stats = BlockClassifier.stats(classifications)
        logger.info(
            "Block 类型分类完成",
            stats=classification_stats,
        )

        section_mappings = await self.chapter_mapping.load(document_id)
        knowledge_count = 0
        question_count = 0
        question_diagnostic: Optional[Dict[str, Any]] = None
        question_unassigned: List[Dict[str, Any]] = []
        answer_linked = 0
        consumed_block_ids: Set[str] = set()

        if extract_questions:
            await cleanup_document_entities(
                self.db,
                document_id,
                "question",
            )
            question_result = await self.question_pipeline.extract(
                document_id=document_id,
                fallback_subject_id=fallback_subject_id,
                blocks=list(blocks),
                section_mappings=section_mappings,
                doc_meta=doc_meta,
                doc_type=self.last_document_type,
            )
            question_count = question_result["saved_count"]
            question_diagnostic = question_result["diagnostic"]
            question_unassigned = question_result.get("unassigned", [])
            consumed_block_ids = set(
                question_result.get("consumed_block_ids") or []
            )
            try:
                answer_linked = (
                    await self.question_persistence.link_extracted_answers(
                        document_id,
                        blocks,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "PDF 答案区回连失败，跳过",
                    document_id=document_id,
                    error=str(exc),
                )

        if extract_knowledge:
            await cleanup_document_entities(
                self.db,
                document_id,
                "knowledge_point",
            )
            knowledge_blocks = select_knowledge_blocks(
                blocks,
                consumed_block_ids,
                block_label_by_id,
            )
            knowledge_count = await self.knowledge_pipeline.extract(
                document_id=document_id,
                fallback_subject_id=fallback_subject_id,
                blocks=knowledge_blocks,
                section_mappings=section_mappings,
            )

        uncovered_pages = find_uncovered_pages(
            blocks,
            section_mappings,
        )
        if uncovered_pages:
            logger.warning(
                "存在未被章节映射覆盖的页码，题目/知识点将依赖前后回退归属",
                document_id=document_id,
                uncovered_pages=uncovered_pages,
            )

        await self.db.commit()
        logger.info(
            "实体抽取完成",
            document_id=document_id,
            knowledge_count=knowledge_count,
            question_count=question_count,
        )
        return {
            "document_id": document_id,
            "knowledge_count": knowledge_count,
            "question_count": question_count,
            "question_diagnostic": question_diagnostic,
            "block_classification": classification_stats,
            "doc_meta": doc_meta,
            "unassigned_questions": question_unassigned,
            "uncovered_pages": uncovered_pages,
            "answer_linked": answer_linked,
        }
