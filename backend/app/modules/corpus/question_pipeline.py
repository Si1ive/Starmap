"""Orchestrate question extraction, repair, diagnostics, and persistence."""

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import Document, DocumentBlock
from app.modules.corpus.document_mapping import PageMappingIndex
from app.modules.corpus.entity_persistence import QuestionPersistence
from app.modules.corpus.extraction_diagnostics import (
    build_question_extraction_diagnostic,
    extract_fix_history,
    question_text_excerpt,
)
from app.modules.corpus.question_builder import (
    QuestionBuilder,
    build_extraction_meta,
    detect_merged_question_nos,
    split_merged_questions,
)
from app.modules.corpus.question_layout import QuestionLayoutGrouper
from app.modules.corpus.question_llm_repair import LLMFallbackFixer
from app.modules.corpus.question_validation import (
    RuleBasedFixer,
    comprehensive_validation,
    extract_question_number,
)
from app.services.llm_client import PDFStructureLLMClient
from app.services.system_settings_service import SystemSettingsService

logger = get_logger(__name__)


class QuestionExtractionPipeline:
    """Run the complete question extraction use case for one document."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.builder = QuestionBuilder(db)
        self.persistence = QuestionPersistence(db)

    async def get_llm_client(self) -> Optional[PDFStructureLLMClient]:
        """Load the independently configured PDF structure LLM."""
        try:
            runtime_settings = await SystemSettingsService(self.db).load()
            llm_config = runtime_settings.get("pdf_structure_llm", {})
            return PDFStructureLLMClient(
                llm_config if isinstance(llm_config, dict) else {}
            )
        except Exception as exc:
            logger.warning(
                "读取PDF结构解析LLM配置失败，跳过LLM兜底",
                error=str(exc),
            )
            return None

    async def extract(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: PageMappingIndex,
        doc_meta: Optional[Dict[str, Any]] = None,
        doc_type: str = "other",
    ) -> Dict[str, Any]:
        """Extract, repair, validate, and persist questions."""
        raw_questions = await self.extract_raw_questions(
            document_id=document_id,
            fallback_subject_id=fallback_subject_id,
            blocks=blocks,
            section_mappings=section_mappings,
            doc_meta=doc_meta,
            doc_type=doc_type,
        )
        logger.info("初步提取 (bbox)", question_count=len(raw_questions))

        if not raw_questions:
            diagnostic = build_question_extraction_diagnostic(
                raw_questions=[],
                final_questions=[],
                validation_report={},
                final_report={},
                saved_results=[],
            )
            return {
                "saved_count": 0,
                "diagnostic": diagnostic,
                "unassigned": [],
                "consumed_block_ids": set(),
            }

        validation_report = comprehensive_validation(raw_questions)
        logger.info(
            "题目初次校验完成",
            issue_count=validation_report["summary"]["total_issues"],
        )

        fixer = RuleBasedFixer()
        questions = fixer.fix_option_issues(
            raw_questions,
            validation_report["option_issues"],
        )
        rule_fixed_count = sum(
            1 for question in questions if question.get("fixed_by_rule")
        )
        logger.info("题目规则修复完成", fixed_count=rule_fixed_count)

        validation_report_v2 = comprehensive_validation(questions)
        if validation_report_v2["summary"]["critical_issues"]:
            llm_client = await self.get_llm_client()
            if llm_client and llm_client.is_available:
                questions = await LLMFallbackFixer(
                    llm_client
                ).fix_remaining_issues(
                    questions,
                    validation_report_v2,
                )
            elif llm_client and llm_client.enabled:
                logger.warning(
                    "PDF结构解析LLM已启用但配置不完整，跳过LLM兜底",
                    provider=llm_client.provider,
                    model=llm_client.model,
                    has_api_key=bool(llm_client.api_key),
                )

        final_report = comprehensive_validation(questions)
        logger.info(
            "题目最终校验完成",
            question_count=len(questions),
            issue_count=final_report["summary"]["total_issues"],
        )

        self._refresh_extraction_metadata(questions)
        diagnostic_report = {
            "initial_report": validation_report,
            "after_rule_fix": validation_report_v2,
            "final_report": final_report,
            "fix_history": extract_fix_history(questions),
        }
        await self.save_diagnostic_report(document_id, diagnostic_report)

        saved_results = []
        for question in questions:
            saved, reason = await self.persistence.save_question(question)
            saved_results.append(
                {
                    "question_id": question.get("id"),
                    "question_no": extract_question_number(question),
                    "page_no": question.get("page_no"),
                    "saved": saved,
                    "reason": reason,
                    "subject_id": question.get("subject_id"),
                    "chapter_id": question.get("chapter_id"),
                    "primary_chapter_id": question.get(
                        "primary_chapter_id"
                    ),
                    "text_excerpt": question_text_excerpt(question),
                }
            )

        saved_count = sum(
            1 for result in saved_results if result["saved"]
        )
        unassigned = [
            {
                "page_no": result.get("page_no"),
                "question_no": result.get("question_no"),
                "reason": result.get("reason"),
                "text_excerpt": result.get("text_excerpt"),
            }
            for result in saved_results
            if result.get("reason") == "saved_unassigned"
        ]
        diagnostic = build_question_extraction_diagnostic(
            raw_questions=raw_questions,
            final_questions=questions,
            validation_report=validation_report,
            final_report=final_report,
            saved_results=saved_results,
        )

        saved_ids = {
            result["question_id"]
            for result in saved_results
            if result["saved"]
        }
        consumed_block_ids = {
            block_id
            for question in questions
            if question.get("id") in saved_ids
            for block_id in question.get("block_ids") or []
        }
        return {
            "saved_count": saved_count,
            "diagnostic": diagnostic,
            "unassigned": unassigned,
            "consumed_block_ids": consumed_block_ids,
        }

    async def extract_raw_questions(
        self,
        document_id: str,
        fallback_subject_id: str,
        blocks: List[DocumentBlock],
        section_mappings: PageMappingIndex,
        doc_meta: Optional[Dict[str, Any]] = None,
        doc_type: str = "other",
    ) -> List[Dict[str, Any]]:
        """Group blocks and split groups that contain successor questions."""
        grouper = QuestionLayoutGrouper(list(blocks))
        groups = grouper.group_into_questions()

        split_llm = await self.get_llm_client()
        split_enabled = bool(split_llm and split_llm.is_available)

        questions: List[Dict[str, Any]] = []
        for group in groups:
            question = await self.builder.group_to_dict(
                document_id=document_id,
                fallback_subject_id=fallback_subject_id,
                group=group,
                section_mappings=section_mappings,
                grouper=grouper,
                doc_meta=doc_meta,
                doc_type=doc_type,
            )
            if not question:
                continue

            base_no = extract_question_number(question)
            successors = detect_merged_question_nos(
                question.get("raw_text") or "",
                base_no,
            )
            if split_enabled and successors:
                parts = await split_merged_questions(
                    split_llm,
                    question.get("raw_text") or "",
                    base_no,
                    successors,
                )
                if parts:
                    logger.info(
                        "LLM 切分多题粘连",
                        base_no=base_no,
                        successors=successors,
                        into=len(parts),
                    )
                    for part in parts:
                        questions.append(
                            await self.builder.build_split_question(
                                question,
                                part,
                            )
                        )
                    continue

            questions.append(question)

        return questions

    async def save_diagnostic_report(
        self,
        document_id: str,
        report: Dict[str, Any],
    ) -> None:
        """Log a compact question extraction diagnostic summary."""
        try:
            result = await self.db.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()
            if document:
                logger.info(
                    "题目抽取诊断",
                    document_id=document_id,
                    initial_issues=report["initial_report"]["summary"][
                        "total_issues"
                    ],
                    final_issues=report["final_report"]["summary"][
                        "total_issues"
                    ],
                    fix_count=len(report["fix_history"]),
                )
        except Exception as exc:
            logger.error(
                "保存诊断报告失败",
                document_id=document_id,
                error=str(exc),
            )

    @staticmethod
    def _refresh_extraction_metadata(
        questions: List[Dict[str, Any]],
    ) -> None:
        """Recompute quality metadata after rule and LLM repairs."""
        for question in questions:
            previous = question.get("extraction_meta") or {}
            current = build_extraction_meta(
                blocks=question.get("blocks") or [],
                options=question.get("options") or [],
                question_type=(
                    question.get("question_type")
                    or question.get("type")
                    or "short_answer"
                ),
                question_no=question.get("question_no"),
                has_figures=bool(question.get("figures")),
                group_label_reason=previous.get("group_label_reason"),
            )
            question["extraction_meta"] = {
                **previous,
                **current,
            }
