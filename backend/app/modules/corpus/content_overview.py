"""Structured corpus content overview and ingestion quality assessment."""

from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import (
    CanonicalChapter,
    Document,
    EntityExtractionRun,
    KnowledgePoint,
    Question,
)


class CorpusContentOverviewService:
    """Load extracted entities and evaluate whether the ingestion needs attention."""

    POLICY_VERSION = "2026-07-v2"
    EXPECTED_OPTION_LABELS = ("A", "B", "C", "D")

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, document_id: str) -> Optional[Dict[str, Any]]:
        document = (
            await self.db.execute(
                select(Document).where(Document.id == document_id)
            )
        ).scalar_one_or_none()
        if not document:
            return None

        knowledge_points = (
            await self.db.execute(
                select(KnowledgePoint)
                .where(
                    KnowledgePoint.source_document_id == document_id,
                    KnowledgePoint.status != "deleted",
                )
                .order_by(KnowledgePoint.created_at, KnowledgePoint.id)
            )
        ).scalars().all()
        questions = (
            await self.db.execute(
                select(Question).where(
                    Question.source_document_id == document_id,
                    Question.status != "deleted",
                )
            )
        ).scalars().all()
        latest_run = (
            await self.db.execute(
                select(EntityExtractionRun)
                .where(
                    EntityExtractionRun.document_id == document_id,
                    EntityExtractionRun.scope == "document",
                )
                .order_by(EntityExtractionRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        entity_runs = (
            await self.db.execute(
                select(EntityExtractionRun)
                .where(
                    EntityExtractionRun.document_id == document_id,
                    EntityExtractionRun.scope == "entity",
                )
                .order_by(EntityExtractionRun.created_at.desc())
            )
        ).scalars().all()
        latest_entity_run_map = self.build_latest_entity_run_map(entity_runs)

        chapter_ids = {
            item.primary_chapter_id
            for item in [*knowledge_points, *questions]
            if item.primary_chapter_id
        }
        chapter_map: Dict[str, CanonicalChapter] = {}
        if chapter_ids:
            chapters = (
                await self.db.execute(
                    select(CanonicalChapter).where(
                        CanonicalChapter.id.in_(list(chapter_ids))
                    )
                )
            ).scalars().all()
            chapter_map = {chapter.id: chapter for chapter in chapters}

        groups: Dict[str, Dict[str, Any]] = {}
        ungrouped_knowledge_points: List[Dict[str, Any]] = []
        for knowledge_point in knowledge_points:
            brief = {
                "id": knowledge_point.id,
                "title": knowledge_point.title,
                "summary": knowledge_point.summary,
                "content_preview": (knowledge_point.content or "")[:300],
                "topic_terms": knowledge_point.topic_terms or [],
                "review_status": knowledge_point.review_status,
                "status": knowledge_point.status,
                "source_section_path": knowledge_point.source_section_path,
                "reextraction": latest_entity_run_map.get(
                    ("knowledge_point", knowledge_point.id)
                ),
            }
            chapter_id = knowledge_point.primary_chapter_id
            if chapter_id and chapter_id in chapter_map:
                if chapter_id not in groups:
                    chapter = chapter_map[chapter_id]
                    groups[chapter_id] = {
                        "chapter_id": chapter_id,
                        "chapter_name": chapter.name,
                        "outline_code": chapter.outline_code,
                        "keywords": chapter.keywords or [],
                        "description": chapter.description,
                        "exam_guidance": chapter.exam_guidance,
                        "knowledge_points": [],
                    }
                groups[chapter_id]["knowledge_points"].append(brief)
            else:
                ungrouped_knowledge_points.append(brief)

        questions_sorted = sorted(questions, key=self._question_sort_key)
        question_items = [
            {
                "id": question.id,
                "question_no": question.question_no,
                "type": question.type,
                "content_preview": (question.content or "")[:300],
                "options": question.options or [],
                "exam_year": question.exam_year,
                "review_status": question.review_status,
                "status": question.status,
                "primary_chapter_id": question.primary_chapter_id,
                "primary_chapter_name": (
                    chapter_map[question.primary_chapter_id].name
                    if question.primary_chapter_id
                    and question.primary_chapter_id in chapter_map
                    else None
                ),
                "source_section_path": question.source_section_path,
                "is_unassigned": self._is_question_unassigned(question),
                "extraction_meta": question.extraction_meta or None,
                "reextraction": latest_entity_run_map.get(
                    ("question", question.id)
                ),
            }
            for question in questions_sorted
        ]
        unassigned_question_count = sum(
            1 for question in questions if self._is_question_unassigned(question)
        )

        summary = {
            "knowledge_count": len(knowledge_points),
            "question_count": len(questions),
            "chapter_count": len(groups),
            "ungrouped_count": len(ungrouped_knowledge_points),
            "unassigned_question_count": unassigned_question_count,
        }
        return {
            "document_id": document.id,
            "title": document.title,
            "doc_type": document.doc_type,
            "knowledge_chapters": list(groups.values()),
            "ungrouped_knowledge_points": ungrouped_knowledge_points,
            "questions": question_items,
            "summary": summary,
            "quality_gate": self.build_quality_gate(
                document=document,
                knowledge_points=knowledge_points,
                questions=questions,
                summary=summary,
                latest_run=latest_run,
            ),
        }

    @staticmethod
    def _question_sort_key(question: Question) -> tuple:
        number = (question.question_no or "").strip()
        digits = "".join(character for character in number if character.isdigit())
        return (0, int(digits)) if digits else (1, number)

    @staticmethod
    def _is_question_unassigned(question: Question) -> bool:
        return not question.subject_id or not question.chapter_id

    @classmethod
    def build_latest_entity_run_map(
        cls,
        runs: Sequence[EntityExtractionRun],
    ) -> Dict[tuple, Dict[str, Any]]:
        """Keep the newest durable task state for each entity target."""
        result: Dict[tuple, Dict[str, Any]] = {}
        for run in runs:
            key = (run.target_entity_type, run.target_entity_id)
            if not all(key) or key in result:
                continue
            result[key] = cls._serialize_entity_run(run)
        return result

    @classmethod
    def build_quality_gate(
        cls,
        *,
        document: Document,
        knowledge_points: Sequence[KnowledgePoint],
        questions: Sequence[Question],
        summary: Dict[str, int],
        latest_run: Optional[EntityExtractionRun],
    ) -> Dict[str, Any]:
        """Build a deterministic quality report from persisted, queryable facts."""
        question_issue_ids = set()
        issues: List[Dict[str, Any]] = []
        llm_repaired_question_count = 0
        recovered_option_count = 0
        ai_generated_option_count = 0
        missing_question_no_count = 0
        original_issue_question_count = 0
        numbered_questions: List[str] = []
        questions_by_number: Dict[str, List[Question]] = {}

        for question in questions:
            options = question.options or []
            meta = question.extraction_meta or {}
            if question.question_no:
                number = str(question.question_no).strip()
                numbered_questions.append(number)
                questions_by_number.setdefault(number, []).append(question)
            else:
                missing_question_no_count += 1
                cls._add_issue(
                    issues,
                    key=f"question-number-missing:{question.id}",
                    check_key="question_numbering",
                    severity="warning",
                    entity_type="question",
                    entity_id=question.id,
                    entity_label=cls._question_label(question),
                    message="未识别出题号，需要核对题干开头或手动补充题号",
                )
            if meta.get("missing_question_no"):
                missing_question_no_count += int(bool(question.question_no))
                if question.question_no:
                    cls._add_issue(
                        issues,
                        key=f"question-number-recovered:{question.id}",
                        check_key="question_numbering",
                        severity="warning",
                        entity_type="question",
                        entity_id=question.id,
                        entity_label=cls._question_label(question),
                        message="抽取时曾缺失题号，当前题号需要对照原卷核验",
                    )

            has_option_issue = (
                question.type == "choice" and len(options) < 4
            ) or bool(meta.get("suspected_truncated_options"))
            if has_option_issue:
                question_issue_ids.add(question.id)
                cls._add_issue(
                    issues,
                    key=f"question-structure:{question.id}",
                    check_key="question_integrity",
                    severity="fail",
                    entity_type="question",
                    entity_id=question.id,
                    entity_label=cls._question_label(question),
                    message=cls._question_integrity_message(
                        question=question,
                        options=options,
                        meta=meta,
                    ),
                )
            if meta.get("fixed_by_llm") or meta.get("llm_fix_actions"):
                llm_repaired_question_count += 1
            if meta.get("original_issues"):
                original_issue_question_count += 1

            ai_generated_labels = []
            for option in options:
                if option.get("source") == "extracted":
                    recovered_option_count += 1
                elif option.get("source") == "ai_generated":
                    ai_generated_option_count += 1
                    label = (
                        option.get("key")
                        or option.get("label")
                        or option.get("option_label")
                    )
                    if label:
                        ai_generated_labels.append(str(label).strip().upper())

            if ai_generated_labels:
                cls._add_issue(
                    issues,
                    key=f"ai-generated-option:{question.id}",
                    check_key="ai_generated_content",
                    severity="warning",
                    entity_type="question",
                    entity_id=question.id,
                    entity_label=cls._question_label(question),
                    message=(
                        f"选项 {cls._join_labels(ai_generated_labels)} 由 AI 生成，"
                        "需要对照原卷核验"
                    ),
                )

            if cls._is_question_unassigned(question):
                cls._add_issue(
                    issues,
                    key=f"question-unassigned:{question.id}",
                    check_key="chapter_assignment",
                    severity="warning",
                    entity_type="question",
                    entity_id=question.id,
                    entity_label=cls._question_label(question),
                    message="尚未完成科目或章节归属",
                )

        for knowledge_point in knowledge_points:
            if knowledge_point.primary_chapter_id:
                continue
            cls._add_issue(
                issues,
                key=f"knowledge-unassigned:{knowledge_point.id}",
                check_key="chapter_assignment",
                severity="warning",
                entity_type="knowledge_point",
                entity_id=knowledge_point.id,
                entity_label=knowledge_point.title or "未命名知识点",
                message="尚未归属标准考点",
            )

        duplicate_question_no_count = sum(
            count - 1
            for count in Counter(numbered_questions).values()
            if count > 1
        )
        for number, duplicate_questions in questions_by_number.items():
            if len(duplicate_questions) < 2:
                continue
            cls._add_issue(
                issues,
                key=f"question-number-duplicate:{number}",
                check_key="question_numbering",
                severity="warning",
                entity_type="question",
                entity_id=duplicate_questions[0].id,
                entity_label=f"第{number}题",
                message=f"该题号共出现 {len(duplicate_questions)} 次，需要确认是否错误拆题",
            )
        run_result = (
            latest_run.result_json
            if latest_run and isinstance(latest_run.result_json, dict)
            else {}
        )
        diagnostic = (
            run_result.get("question_diagnostic")
            if isinstance(run_result.get("question_diagnostic"), dict)
            else {}
        )
        validation = (
            diagnostic.get("validation")
            if isinstance(diagnostic.get("validation"), dict)
            else {}
        )
        skipped_question_count = cls._as_non_negative_int(
            diagnostic.get("skipped_question_count")
        )
        initial_issue_count = cls._as_non_negative_int(
            validation.get("initial_issue_count")
        )
        final_issue_count = cls._as_non_negative_int(
            validation.get("final_issue_count")
        )
        unsaved_samples = (
            diagnostic.get("unsaved_samples")
            if isinstance(diagnostic.get("unsaved_samples"), list)
            else []
        )
        for index, sample in enumerate(unsaved_samples):
            if not isinstance(sample, dict):
                continue
            cls._add_issue(
                issues,
                key=f"question-unsaved:{index}",
                check_key="save_integrity",
                severity="fail",
                entity_type="extraction_result",
                entity_id=None,
                entity_label=cls._unsaved_question_label(sample),
                message=cls._unsaved_question_message(sample),
            )
        # The document-run aggregate is historical after targeted re-extraction.
        # Current persisted entities and explicit unsaved samples are the gate's
        # source of truth, so a repaired question can immediately clear its issue.
        unresolved_question_count = len(question_issue_ids)

        metrics = {
            **summary,
            "unresolved_question_count": unresolved_question_count,
            "missing_question_no_count": missing_question_no_count,
            "duplicate_question_no_count": duplicate_question_no_count,
            "skipped_question_count": skipped_question_count,
            "initial_issue_count": initial_issue_count,
            "final_issue_count": final_issue_count,
            "llm_repaired_question_count": llm_repaired_question_count,
            "original_issue_question_count": original_issue_question_count,
            "recovered_option_count": recovered_option_count,
            "ai_generated_option_count": ai_generated_option_count,
        }
        checks: List[Dict[str, Any]] = []

        if not latest_run:
            cls._add_check(
                checks,
                key="extraction_run",
                label="抽取任务",
                status="warning" if questions or knowledge_points else "pending",
                message=(
                    "存在历史内容，但没有可追溯的抽取任务记录"
                    if questions or knowledge_points
                    else "尚未执行实体抽取"
                ),
            )
        elif latest_run.status == "running":
            cls._add_check(
                checks,
                key="extraction_run",
                label="抽取任务",
                status="running",
                message="最新实体抽取任务仍在执行",
            )
        elif latest_run.status == "failed":
            cls._add_check(
                checks,
                key="extraction_run",
                label="抽取任务",
                status="fail",
                message=latest_run.error_detail or "最新实体抽取任务失败",
            )
        else:
            cls._add_check(
                checks,
                key="extraction_run",
                label="抽取任务",
                status="pass",
                message="最新实体抽取任务已成功完成",
            )

        content_status, content_message = cls._content_yield_check(
            document=document,
            latest_run=latest_run,
            knowledge_count=len(knowledge_points),
            question_count=len(questions),
        )
        cls._add_check(
            checks,
            key="content_yield",
            label="内容产出",
            status=content_status,
            message=content_message,
        )
        cls._add_check(
            checks,
            key="question_integrity",
            label="题目完整性",
            status="fail" if unresolved_question_count else "pass",
            message=(
                f"仍有 {unresolved_question_count} 道题存在选项或关键结构问题"
                if unresolved_question_count
                else "未发现未解决的题目结构问题"
            ),
        )
        cls._add_check(
            checks,
            key="save_integrity",
            label="题目落库",
            status="fail" if skipped_question_count else "pass",
            message=(
                f"本次抽取有 {skipped_question_count} 道题未成功落库"
                if skipped_question_count
                else "本次诊断未发现题目落库丢失"
            ),
        )

        unassigned_count = summary["unassigned_question_count"]
        ungrouped_count = summary["ungrouped_count"]
        assignment_issue_count = unassigned_count + ungrouped_count
        cls._add_check(
            checks,
            key="chapter_assignment",
            label="章节归属",
            status="warning" if assignment_issue_count else "pass",
            message=(
                f"{unassigned_count} 道题、{ungrouped_count} 个知识点尚未完成章节归属"
                if assignment_issue_count
                else "题目和知识点均已完成章节归属"
            ),
        )

        numbering_issue_count = (
            missing_question_no_count + duplicate_question_no_count
        )
        cls._add_check(
            checks,
            key="question_numbering",
            label="题号质量",
            status="warning" if numbering_issue_count else "pass",
            message=(
                f"缺失题号 {missing_question_no_count} 道，重复题号 "
                f"{duplicate_question_no_count} 道"
                if numbering_issue_count
                else "未发现题号缺失或重复"
            ),
        )
        cls._add_check(
            checks,
            key="ai_generated_content",
            label="AI 生成内容",
            status="warning" if ai_generated_option_count else "pass",
            message=(
                f"{ai_generated_option_count} 个选项由 AI 生成，建议优先人工核验"
                if ai_generated_option_count
                else "没有 AI 生成选项"
            ),
        )

        status = cls._overall_status(checks, latest_run, questions, knowledge_points)
        score = cls._quality_score(
            status=status,
            content_yield_failed=content_status == "fail",
            unresolved_question_count=unresolved_question_count,
            skipped_question_count=skipped_question_count,
            unassigned_question_count=unassigned_count,
            ungrouped_count=ungrouped_count,
            numbering_issue_count=numbering_issue_count,
            ai_generated_option_count=ai_generated_option_count,
        )
        fail_count = sum(1 for check in checks if check["status"] == "fail")
        warning_count = sum(
            1 for check in checks if check["status"] == "warning"
        )
        issues.sort(
            key=lambda issue: (
                issue["severity"] != "fail",
                issue["entity_label"],
                issue["key"],
            )
        )

        return {
            "policy_version": cls.POLICY_VERSION,
            "status": status,
            "label": cls._status_label(status),
            "score": score,
            "summary": cls._status_summary(status, fail_count, warning_count),
            "manual_review_required": status in {"blocked", "failed", "warning"},
            "metrics": metrics,
            "checks": checks,
            "issues": issues,
            "latest_run": cls._serialize_latest_run(latest_run),
        }

    @classmethod
    def _question_integrity_message(
        cls,
        *,
        question: Question,
        options: Sequence[Dict[str, Any]],
        meta: Dict[str, Any],
    ) -> str:
        reasons = []
        if question.type == "choice" and len(options) < 4:
            labels = {
                str(
                    option.get("key")
                    or option.get("label")
                    or option.get("option_label")
                    or ""
                ).strip().upper()[:1]
                for option in options
            }
            labels.discard("")
            missing_labels = [
                label
                for label in cls.EXPECTED_OPTION_LABELS
                if label not in labels
            ]
            if labels and missing_labels:
                reasons.append(
                    f"仅识别到选项 {cls._join_labels(sorted(labels))}，"
                    f"缺少 {cls._join_labels(missing_labels)}"
                )
            else:
                reasons.append(
                    f"选择题仅识别到 {len(options)} 个选项，选项结构不完整"
                )
        if meta.get("suspected_truncated_options"):
            reasons.append("存在疑似被截断的选项文本")
        return "；".join(reasons) or "题目存在未解决的关键结构问题"

    @staticmethod
    def _question_label(question: Question) -> str:
        number = str(getattr(question, "question_no", "") or "").strip()
        if number:
            return f"第{number}题"
        content = str(getattr(question, "content", "") or "").strip()
        excerpt = content[:18] + ("..." if len(content) > 18 else "")
        return f"无题号题目：{excerpt}" if excerpt else "无题号题目"

    @staticmethod
    def _join_labels(labels: Sequence[str]) -> str:
        return "、".join(dict.fromkeys(label for label in labels if label))

    @staticmethod
    def _unsaved_question_label(sample: Dict[str, Any]) -> str:
        number = sample.get("question_no")
        if number is not None:
            return f"第{number}题"
        page_no = sample.get("page_no")
        return f"第{page_no}页题目" if page_no is not None else "未落库题目"

    @staticmethod
    def _unsaved_question_message(sample: Dict[str, Any]) -> str:
        reason_text = {
            "save_failed": "数据库保存失败",
            "missing_subject": "缺少科目归属",
            "missing_chapter": "缺少章节归属",
        }.get(sample.get("reason"), sample.get("reason") or "未知原因")
        excerpt = str(sample.get("text_excerpt") or "").strip()
        if excerpt:
            excerpt = excerpt[:60] + ("..." if len(excerpt) > 60 else "")
            return f"未成功入库：{reason_text}；题干：{excerpt}"
        return f"未成功入库：{reason_text}"

    @staticmethod
    def _add_issue(
        issues: List[Dict[str, Any]],
        *,
        key: str,
        check_key: str,
        severity: str,
        entity_type: str,
        entity_id: Optional[str],
        entity_label: str,
        message: str,
    ) -> None:
        issues.append(
            {
                "key": key,
                "check_key": check_key,
                "severity": severity,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_label": entity_label,
                "message": message,
            }
        )

    @staticmethod
    def _content_yield_check(
        *,
        document: Document,
        latest_run: Optional[EntityExtractionRun],
        knowledge_count: int,
        question_count: int,
    ) -> tuple:
        if latest_run and latest_run.status == "running":
            return "running", "抽取执行中，内容产出尚未稳定"
        if not latest_run and not knowledge_count and not question_count:
            return "pending", "尚无可评估的入库内容"

        doc_type = document.doc_type or "other"
        if doc_type in {"past_exam", "mock_exam"} and question_count == 0:
            return "fail", "试卷类文档没有产出题目"
        if doc_type in {"textbook", "notes"} and knowledge_count == 0:
            return "fail", "教材或笔记类文档没有产出知识点"
        if knowledge_count + question_count == 0:
            return "fail", "抽取任务没有产出任何知识点或题目"
        return (
            "pass",
            f"已产出 {knowledge_count} 个知识点、{question_count} 道题目",
        )

    @staticmethod
    def _add_check(
        checks: List[Dict[str, Any]],
        *,
        key: str,
        label: str,
        status: str,
        message: str,
    ) -> None:
        checks.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "message": message,
            }
        )

    @staticmethod
    def _overall_status(
        checks: Sequence[Dict[str, Any]],
        latest_run: Optional[EntityExtractionRun],
        questions: Sequence[Question],
        knowledge_points: Sequence[KnowledgePoint],
    ) -> str:
        if latest_run and latest_run.status == "running":
            return "running"
        if latest_run and latest_run.status == "failed":
            return "failed"
        if any(check["status"] == "fail" for check in checks):
            return "blocked"
        if any(check["status"] == "warning" for check in checks):
            return "warning"
        if not latest_run and not questions and not knowledge_points:
            return "not_run"
        return "passed"

    @staticmethod
    def _quality_score(
        *,
        status: str,
        content_yield_failed: bool,
        unresolved_question_count: int,
        skipped_question_count: int,
        unassigned_question_count: int,
        ungrouped_count: int,
        numbering_issue_count: int,
        ai_generated_option_count: int,
    ) -> int:
        if status == "not_run":
            return 0
        score = 100
        score -= 40 if content_yield_failed else 0
        score -= min(45, unresolved_question_count * 15)
        score -= min(30, skipped_question_count * 10)
        score -= min(20, unassigned_question_count * 4)
        score -= min(15, ungrouped_count * 3)
        score -= min(10, numbering_issue_count * 3)
        score -= min(10, ai_generated_option_count * 2)
        if status == "failed":
            score = min(score, 40)
        return max(0, score)

    @staticmethod
    def _status_label(status: str) -> str:
        return {
            "passed": "质量通过",
            "warning": "建议核验",
            "blocked": "需要修复",
            "running": "评估中",
            "failed": "抽取失败",
            "not_run": "尚未抽取",
        }[status]

    @staticmethod
    def _status_summary(status: str, fail_count: int, warning_count: int) -> str:
        if status == "passed":
            return "当前入库产物通过全部质量检查。"
        if status == "warning":
            return f"没有阻断问题，但有 {warning_count} 项需要人工关注。"
        if status == "blocked":
            return f"发现 {fail_count} 项阻断问题，建议修复后重新抽取。"
        if status == "running":
            return "抽取任务仍在执行，完成后将自动形成最终质量结论。"
        if status == "failed":
            return "最新抽取任务失败，当前内容可能来自更早的执行结果。"
        return "尚未执行实体抽取，暂无质量结论。"

    @staticmethod
    def _serialize_latest_run(
        latest_run: Optional[EntityExtractionRun],
    ) -> Optional[Dict[str, Any]]:
        if not latest_run:
            return None
        return {
            "id": latest_run.id,
            "status": latest_run.status,
            "knowledge_count": latest_run.knowledge_count or 0,
            "question_count": latest_run.question_count or 0,
            "error_detail": latest_run.error_detail,
            "started_at": (
                latest_run.started_at.isoformat()
                if latest_run.started_at
                else None
            ),
            "completed_at": (
                latest_run.completed_at.isoformat()
                if latest_run.completed_at
                else None
            ),
        }

    @staticmethod
    def _serialize_entity_run(
        run: EntityExtractionRun,
    ) -> Dict[str, Any]:
        return {
            "id": run.id,
            "status": run.status,
            "scope": run.scope,
            "target_entity_type": run.target_entity_type,
            "target_entity_id": run.target_entity_id,
            "error_detail": run.error_detail,
            "result": run.result_json,
            "started_at": (
                run.started_at.isoformat() if run.started_at else None
            ),
            "completed_at": (
                run.completed_at.isoformat() if run.completed_at else None
            ),
        }

    @staticmethod
    def _as_non_negative_int(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0
