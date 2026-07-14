"""
实体抽取服务

从文档的 blocks 中抽取知识点和题目，生成 knowledge_points 和 questions 记录。
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.corpus.document_mapping import (
    DocumentChapterMappingResolver,
)
from app.modules.corpus.entity_persistence import (
    KnowledgePointPersistence,
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
    CorpusFile,
    Document,
    DocumentBlock,
    EntityExtractionRun,
)
from app.services.text_cleaning import clean_block_text
from app.services.llm_client import PDFStructureLLMClient

logger = get_logger(__name__)


def clean_punctuation_subscript(text: str) -> str:
    """兼容入口：转发到 text_cleaning.clean_block_text"""
    return clean_block_text(text) or ""


def clean_blocks_punctuation(blocks):
    """清理 blocks 的 content_text/content_md 字段"""
    for block in blocks:
        if block.content_text:
            block.content_text = clean_block_text(block.content_text)
        if block.content_md:
            block.content_md = clean_block_text(block.content_md)
    return blocks


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
        self._knowledge_persistence = KnowledgePointPersistence(db)
        self._question_persistence = QuestionPersistence(db)
        self._question_builder = QuestionBuilder(db)
        self._question_pipeline = QuestionExtractionPipeline(db)

    async def extract_entities_with_run_id(self, run_id: str) -> Dict[str, Any]:
        """执行已创建的抽取任务，并将最终状态持久化到运行记录。"""
        run = await self.db.get(EntityExtractionRun, run_id)
        if not run:
            raise ValueError(f"抽取任务不存在: {run_id}")

        try:
            await self._set_corpus_file_status(run.document_id, "extracting")
            await self.db.commit()

            result = await self.extract_entities(
                document_id=run.document_id,
                extract_knowledge=run.extract_knowledge,
                extract_questions=run.extract_questions,
                fallback_subject_id=run.subject_id,
            )
            indexing_result = await self._index_document_entities(
                document_id=run.document_id,
                include_knowledge=run.extract_knowledge,
                include_questions=run.extract_questions,
            )
            result = {**result, "indexing": indexing_result}

            run.status = "success"
            run.knowledge_count = int(result.get("knowledge_count") or 0)
            run.question_count = int(result.get("question_count") or 0)
            run.result_json = json.loads(
                json.dumps(result, ensure_ascii=False, default=str)
            )
            run.error_detail = None
            run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self._set_corpus_file_status(run.document_id, "indexed")
            await self.db.commit()
            return result
        except Exception as exc:
            await self.db.rollback()
            failed_run = await self.db.get(EntityExtractionRun, run_id)
            if failed_run:
                failed_run.status = "failed"
                failed_run.error_detail = str(exc)[:4000]
                failed_run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await self._set_corpus_file_status(
                    failed_run.document_id,
                    "failed",
                    error_detail=str(exc)[:4000],
                )
                await self.db.commit()
            raise

    async def _index_document_entities(
        self,
        document_id: str,
        include_knowledge: bool,
        include_questions: bool,
    ) -> Dict[str, Any]:
        """将本次抽取产物立即构建为可检索 segments。"""
        from app.services.segment_service import SegmentService

        return await SegmentService(self.db).build_document_segments(
            document_id=document_id,
            include_knowledge=include_knowledge,
            include_questions=include_questions,
            rebuild=True,
        )

    async def _set_corpus_file_status(
        self,
        document_id: str,
        status: str,
        error_detail: Optional[str] = None,
    ) -> None:
        document = await self.db.get(Document, document_id)
        if not document or not document.corpus_file_id:
            return

        corpus_file = await self.db.get(CorpusFile, document.corpus_file_id)
        if not corpus_file:
            return

        corpus_file.status = status
        corpus_file.error_detail = error_detail

    async def extract_entities(
        self,
        document_id: str,
        extract_knowledge: bool = True,
        extract_questions: bool = True,
        fallback_subject_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        从文档中抽取实体

        学科归属从章节映射反推（canonical_chapter.subject_id），
        不依赖 document.subject_id，因此同一文档的不同 section 可以属于不同学科。

        Args:
            document_id: 文档ID
            extract_knowledge: 是否抽取知识点
            extract_questions: 是否抽取题目

        Returns:
            抽取结果统计
        """
        # 1. 获取文档信息
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            raise ValueError(f"文档不存在: {document_id}")

        # document.subject_id 仅作为 fallback；前端可在试卷类文档中显式传入学科。
        fallback_subject_id = fallback_subject_id or document.subject_id

        # 1.5 提取文档级来源元信息（年份/真题/机构/试卷名），广播到题目
        from app.services.document_meta_service import DocumentMetaService
        try:
            self._doc_meta = await DocumentMetaService(self.db).extract_and_store_meta(document_id)
        except Exception as e:
            logger.warning("文档元信息提取失败，题目来源将留空", document_id=document_id, error=str(e))
            self._doc_meta = {}
        self._doc_type = document.doc_type or "other"

        # 2. 获取 blocks
        blocks_result = await self.db.execute(
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
        )
        blocks = blocks_result.scalars().all()

        if not blocks:
            return {
                "knowledge_count": 0,
                "question_count": 0,
                "question_diagnostic": None,
                "message": "文档没有 blocks",
            }

        # 2.5 清洗 <sub>/<sup> 标签和多余空白，知识点和题目两条路径共用
        blocks = clean_blocks_punctuation(blocks)

        # 2.6 混排识别：把每个 block 标记为 knowledge / question_stem / question_option / answer 等
        from app.services.block_classifier import BlockClassifier
        classifier_llm = await self._get_pdf_structure_llm_client()
        classifier = BlockClassifier(llm_client=classifier_llm)
        classifications = await classifier.classify(blocks, use_llm=bool(classifier_llm and classifier_llm.is_available))
        block_label_by_id = {c.block_id: c.label for c in classifications if c.block_id}
        classification_stats = BlockClassifier.stats(classifications)
        logger.info("Block 类型分类完成", stats=classification_stats)

        # 3. 获取 section 映射，用于确定章节和学科归属
        # page -> {chapter_id, subject_id}
        section_mappings = await self._get_section_mappings(document_id)

        knowledge_count = 0
        question_count = 0
        question_diagnostic: Optional[Dict[str, Any]] = None
        question_unassigned: List[Dict[str, Any]] = []
        answer_linked = 0

        # 架构：先组题再判类型。题目路径吃全部文本 block（不再按分类器预过滤，
        # 避免题目 block 被误判成 knowledge 而在组题前就被滤掉）。组题后由
        # QuestionLayoutGrouper.classify_group 按"有选项/题号/疑问特征"判定是否题目，
        # 非题目组不落为题目、其 block 留给知识点路径。
        # block_label_by_id 仅用于诊断展示，不再决定分流。
        consumed_block_ids: set = set()

        # 4. 抽取题目 — 吃全部 block，组题后判类型
        if extract_questions:
            await self._cleanup_existing_entities(document_id, "question")
            question_result = await self._extract_questions(
                document_id, fallback_subject_id, list(blocks), section_mappings
            )
            question_count = question_result["saved_count"]
            question_diagnostic = question_result["diagnostic"]
            question_unassigned = question_result.get("unassigned", [])
            consumed_block_ids = set(question_result.get("consumed_block_ids") or [])
            # 4.1 PDF 自带答案区回连：扫描"参考答案"段，按题号写回 answer（标 extracted）
            try:
                answer_linked = await self._extract_and_link_answers(document_id, blocks)
            except Exception as e:
                logger.warning("PDF 答案区回连失败，跳过", document_id=document_id, error=str(e))
                answer_linked = 0

        # 5. 抽取知识点 — 用剩余 block（排除已被题目消费的），保留标题/段落结构
        if extract_knowledge:
            await self._cleanup_existing_entities(document_id, "knowledge_point")
            knowledge_blocks = [
                b for b in blocks
                if getattr(b, "id", None) not in consumed_block_ids
                and block_label_by_id.get(getattr(b, "id", ""), "") in ("knowledge", "heading", "table", "figure", "formula")
            ] or [b for b in blocks if getattr(b, "id", None) not in consumed_block_ids]
            knowledge_count = await self._extract_knowledge_points(
                document_id, fallback_subject_id, knowledge_blocks, section_mappings
            )

        # 跨页归属加固：找出未被任何 section 覆盖的页码（标题漏检/映射失败的信号）
        all_pages = sorted({b.page_no for b in blocks if b.page_no is not None})
        covered_pages = set(section_mappings.keys())
        uncovered_pages = [p for p in all_pages if p not in covered_pages]
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
            "doc_meta": getattr(self, "_doc_meta", {}) or {},
            "unassigned_questions": question_unassigned,
            "uncovered_pages": uncovered_pages,
            "answer_linked": answer_linked,
        }

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
        """抽取知识点"""
        knowledge_count = 0

        # 简单策略：将连续的 paragraph + title blocks 组合为知识点
        current_title = None
        current_content_blocks = []

        for block in blocks:
            # 如果是标题类型，保存前一个知识点并开始新的
            if block.block_type in ('title', 'heading'):
                # 保存前一个知识点
                if current_title and current_content_blocks:
                    created = await self._save_knowledge_point(
                        document_id, fallback_subject_id, current_title,
                        current_content_blocks, section_mappings
                    )
                    if created:
                        knowledge_count += 1
                    current_content_blocks = []

                current_title = block
            elif block.block_type in ('paragraph', 'list'):
                current_content_blocks.append(block)

        # 保存最后一个知识点
        if current_title and current_content_blocks:
            created = await self._save_knowledge_point(
                document_id, fallback_subject_id, current_title,
                current_content_blocks, section_mappings
            )
            if created:
                knowledge_count += 1

        return knowledge_count

    async def _save_knowledge_point(
        self,
        document_id: str,
        fallback_subject_id: str,
        title_block: DocumentBlock,
        content_blocks: List[DocumentBlock],
        section_mappings: Dict[int, Dict[str, Optional[str]]],
    ) -> bool:
        """兼容入口：解析页映射后委托知识点持久化组件。"""
        mapping_info = self._resolve_mapping_for_page(title_block.page_no, section_mappings)
        return await self._knowledge_persistence.save_knowledge_point(
            document_id=document_id,
            fallback_subject_id=fallback_subject_id,
            title_block=title_block,
            content_blocks=content_blocks,
            mapping_info=mapping_info,
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
