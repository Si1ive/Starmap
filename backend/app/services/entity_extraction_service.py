"""
实体抽取服务

从文档的 blocks 中抽取知识点和题目，生成 knowledge_points 和 questions 记录。
"""

from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.corpus.document_mapping import (
    DocumentChapterMappingResolver,
)
from app.modules.corpus.entity_extraction_pipeline import (
    DocumentEntityExtractionPipeline,
    clean_document_blocks,
)
from app.modules.corpus.entity_persistence import (
    QuestionPersistence,
    cleanup_document_entities,
    extract_topic_terms,
    normalize_options,
    strip_leading_option_marker,
)
from app.modules.corpus.extraction_diagnostics import (
    build_question_extraction_diagnostic,
    extract_fix_history,
    question_numbering_summary,
    question_text_excerpt,
)
from app.modules.corpus.extraction_tasks import EntityExtractionRunExecutor
from app.modules.corpus.knowledge_pipeline import KnowledgeExtractionPipeline
from app.modules.corpus.question_builder import (
    QuestionBuilder,
    build_extraction_meta,
    detect_merged_question_nos,
    split_merged_questions,
)
from app.modules.corpus.question_llm_repair import LLMFallbackFixer
from app.modules.corpus.question_layout import (
    BlockTag,
    CHOICE_BLANK_RE,
    COLUMN_GAP_MIN,
    COLUMN_MIN_BLOCKS_PER_COL,
    EMBEDDED_QUESTION_NUMERIC_RE,
    GAP_RATIO_CONTINUATION,
    GAP_RATIO_NEW_QUESTION,
    GAP_RATIO_PAREN_Q,
    LEFT_EDGE_MARGIN,
    OPTION_BLOCK_RE,
    OPTION_MARKER_RE,
    OPTION_SEPARATOR_RE,
    PageStats,
    QUESTION_CUE_RE,
    QUESTION_EXAMPLE_RE,
    QUESTION_NUMERIC_RE,
    QUESTION_PAREN_RE,
    QUESTION_TITLE_RE,
    QuestionGroup,
    QuestionLayoutGrouper,
)
from app.modules.corpus.question_pipeline import QuestionExtractionPipeline
from app.modules.corpus.question_validation import (
    OptionIntegrityChecker,
    QuestionNumberChecker,
    RuleBasedFixer,
    comprehensive_validation,
)
from app.models.mysql_models import (
    DocumentBlock,
)
from app.services.text_cleaning import clean_block_text
from app.services.llm_client import PDFStructureLLMClient


def clean_punctuation_subscript(text: str) -> str:
    """兼容入口：转发到 text_cleaning.clean_block_text"""
    return clean_block_text(text) or ""


def clean_blocks_punctuation(blocks):
    """兼容入口：清理 blocks 的文本字段。"""
    return clean_document_blocks(blocks)


class EntityExtractionService:
    """实体抽取服务"""

    _build_question_extraction_diagnostic = staticmethod(
        build_question_extraction_diagnostic
    )
    _question_numbering_summary = staticmethod(question_numbering_summary)
    _question_text_excerpt = staticmethod(question_text_excerpt)
    _extract_fix_history = staticmethod(extract_fix_history)
    _strip_leading_option_marker = staticmethod(strip_leading_option_marker)
    _normalize_options = staticmethod(normalize_options)
    _extract_topic_terms = staticmethod(extract_topic_terms)
    _detect_merged_question_nos = staticmethod(detect_merged_question_nos)
    _build_extraction_meta = staticmethod(build_extraction_meta)

    def __init__(self, db: AsyncSession):
        self.db = db
        self._chapter_mapping = DocumentChapterMappingResolver(db)
        self._knowledge_pipeline = KnowledgeExtractionPipeline(db)
        self._question_persistence = QuestionPersistence(db)
        self._question_builder = QuestionBuilder(db)
        self._question_pipeline = QuestionExtractionPipeline(db)
        self._document_pipeline = DocumentEntityExtractionPipeline(
            db,
            chapter_mapping=self._chapter_mapping,
            knowledge_pipeline=self._knowledge_pipeline,
            question_pipeline=self._question_pipeline,
            question_persistence=self._question_persistence,
        )
        self._run_executor = EntityExtractionRunExecutor(
            db,
            pipeline=self._document_pipeline,
        )

    async def extract_entities_with_run_id(self, run_id: str) -> Dict[str, Any]:
        """兼容入口：执行已创建的持久化抽取任务。"""
        return await self._run_executor.execute(run_id)

    async def _index_document_entities(
        self,
        document_id: str,
        include_knowledge: bool,
        include_questions: bool,
    ) -> Dict[str, Any]:
        """兼容入口：构建本次抽取产物的检索 segments。"""
        return await self._run_executor.index_document_entities(
            document_id,
            include_knowledge,
            include_questions,
        )

    async def _set_corpus_file_status(
        self,
        document_id: str,
        status: str,
        error_detail: Optional[str] = None,
    ) -> None:
        """兼容入口：更新文档对应语料文件状态。"""
        await self._run_executor.set_corpus_file_status(
            document_id,
            status,
            error_detail,
        )

    async def extract_entities(
        self,
        document_id: str,
        extract_knowledge: bool = True,
        extract_questions: bool = True,
        fallback_subject_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """兼容入口：委托文档级实体抽取流水线。"""
        result = await self._document_pipeline.extract(
            document_id=document_id,
            extract_knowledge=extract_knowledge,
            extract_questions=extract_questions,
            fallback_subject_id=fallback_subject_id,
        )
        self._doc_meta = result.get("doc_meta") or {}
        self._doc_type = self._document_pipeline.last_document_type
        return result

    async def _get_section_mappings(self, document_id: str) -> Dict[int, Dict[str, Optional[str]]]:
        """兼容入口：加载已审核的 section 到章节映射。"""
        return await self._chapter_mapping.load(document_id)

    def _resolve_mapping_for_page(
        self,
        page_no: Optional[int],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> Optional[Dict[str, Optional[str]]]:
        """兼容入口：按页码解析章节映射。"""
        return self._chapter_mapping.resolve(page_no, section_mappings)

    async def _cleanup_existing_entities(self, document_id: str, entity_type: str) -> None:
        """清理同一文档已抽取的实体，避免重复入库。"""
        await cleanup_document_entities(self.db, document_id, entity_type)

    async def _extract_knowledge_points(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> int:
        """兼容入口：委托知识点抽取流水线。"""
        return await self._knowledge_pipeline.extract(
            document_id=document_id,
            fallback_subject_id=fallback_subject_id,
            blocks=blocks,
            section_mappings=section_mappings,
        )

    async def _save_knowledge_point(
        self,
        document_id: str,
        fallback_subject_id: str,
        title_block: DocumentBlock,
        content_blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> bool:
        """兼容入口：委托知识点流水线保存单个分组。"""
        return await self._knowledge_pipeline.save_group(
            document_id=document_id,
            fallback_subject_id=fallback_subject_id,
            title_block=title_block,
            content_blocks=content_blocks,
            section_mappings=section_mappings,
        )

    async def _extract_questions(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> Dict[str, Any]:
        """兼容入口：委托题目抽取流水线。"""
        return await self._question_pipeline.extract(
            document_id=document_id,
            fallback_subject_id=fallback_subject_id,
            blocks=blocks,
            section_mappings=section_mappings,
            doc_meta=getattr(self, "_doc_meta", {}) or {},
            doc_type=getattr(self, "_doc_type", "other"),
        )

    async def _get_pdf_structure_llm_client(self) -> Optional[PDFStructureLLMClient]:
        """兼容入口：读取 PDF 结构解析专用 LLM 配置。"""
        return await self._question_pipeline.get_llm_client()

    async def _llm_split_merged_questions(
        self,
        llm_client: "PDFStructureLLMClient",
        raw_text: str,
        base_no: int,
        successor_nos: List[int],
    ) -> Optional[List[Dict[str, Any]]]:
        """兼容入口：委托题目构建模块完成粘连切分。"""
        return await split_merged_questions(
            llm_client,
            raw_text,
            base_no,
            successor_nos,
        )

    async def _extract_questions_v2(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> List[Dict[str, Any]]:
        """兼容入口：委托题目流水线完成 bbox 分组和粘连切分。"""
        return await self._question_pipeline.extract_raw_questions(
            document_id=document_id,
            fallback_subject_id=fallback_subject_id,
            blocks=blocks,
            section_mappings=section_mappings,
            doc_meta=getattr(self, "_doc_meta", {}) or {},
            doc_type=getattr(self, "_doc_type", "other"),
        )

    async def _build_split_question(
        self,
        document_id: str,
        fallback_subject_id: str,
        base: Dict[str, Any],
        part: Dict[str, Any],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> Dict[str, Any]:
        """兼容入口：委托题目构建模块生成切分后的题目。"""
        return await self._question_builder.build_split_question(base, part)

    async def _question_group_to_dict(
        self,
        document_id: str,
        fallback_subject_id: str,
        group: QuestionGroup,
        section_mappings: Dict[int, Dict[str, Optional[str]]],
        grouper: QuestionLayoutGrouper,
    ) -> Optional[Dict[str, Any]]:
        """兼容入口：委托题目构建模块生成标准题目字典。"""
        return await self._question_builder.group_to_dict(
            document_id=document_id,
            fallback_subject_id=fallback_subject_id,
            group=group,
            section_mappings=section_mappings,
            grouper=grouper,
            doc_meta=getattr(self, "_doc_meta", {}) or {},
            doc_type=getattr(self, "_doc_type", "other"),
        )

    async def _save_question_from_dict(self, question_dict: Dict[str, Any]) -> Tuple[bool, str]:
        """兼容入口：委托题目持久化组件。"""
        return await self._question_persistence.save_question(question_dict)

    async def _extract_and_link_answers(
        self, document_id: str, blocks: List[DocumentBlock]
    ) -> int:
        """兼容入口：委托答案回连组件。"""
        return await self._question_persistence.link_extracted_answers(
            document_id,
            blocks,
        )

    async def _save_diagnostic_report(self, document_id: str, report: Dict[str, Any]) -> None:
        """兼容入口：委托题目流水线记录诊断报告。"""
        await self._question_pipeline.save_diagnostic_report(
            document_id,
            report,
        )

    async def get_entity_source_links(
        self,
        entity_type: str,
        entity_id: str
    ) -> List[Dict[str, Any]]:
        """兼容入口：委托来源引用查询组件。"""
        return await self._question_persistence.get_source_links(
            entity_type,
            entity_id,
        )
