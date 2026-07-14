"""Corpus ingestion quality gate rules."""

from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

from app.models.mysql_models import (
    Document,
    EntityExtractionRun,
    KnowledgePoint,
    Question,
)
from app.modules.corpus.quality_gate_rules import (
    EXPECTED_OPTION_LABELS,
    add_check,
    add_issue,
    as_non_negative_int,
    content_yield_check,
    is_question_unassigned,
    join_labels,
    overall_status,
    quality_score,
    question_integrity_message,
    question_label,
    serialize_latest_run,
    status_label,
    status_summary,
    unsaved_question_label,
    unsaved_question_message,
)


class CorpusQualityGateBuilder:
    """Evaluate persisted corpus entities against deterministic quality rules."""

    POLICY_VERSION = "2026-07-v2"
    EXPECTED_OPTION_LABELS = EXPECTED_OPTION_LABELS

    @staticmethod
    def _is_question_unassigned(question: Question) -> bool:
        return is_question_unassigned(question)

    @classmethod
    def build(
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

            has_option_issue = (question.type == "choice" and len(options) < 4) or bool(
                meta.get("suspected_truncated_options")
            )
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
            count - 1 for count in Counter(numbered_questions).values() if count > 1
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

        numbering_issue_count = missing_question_no_count + duplicate_question_no_count
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
        warning_count = sum(1 for check in checks if check["status"] == "warning")
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
        return question_integrity_message(
            question=question,
            options=options,
            meta=meta,
            expected_option_labels=cls.EXPECTED_OPTION_LABELS,
        )

    @staticmethod
    def _question_label(question: Question) -> str:
        return question_label(question)

    @staticmethod
    def _join_labels(labels: Sequence[str]) -> str:
        return join_labels(labels)

    @staticmethod
    def _unsaved_question_label(sample: Dict[str, Any]) -> str:
        return unsaved_question_label(sample)

    @staticmethod
    def _unsaved_question_message(sample: Dict[str, Any]) -> str:
        return unsaved_question_message(sample)

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
        add_issue(
            issues,
            key=key,
            check_key=check_key,
            severity=severity,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_label=entity_label,
            message=message,
        )

    @staticmethod
    def _content_yield_check(
        *,
        document: Document,
        latest_run: Optional[EntityExtractionRun],
        knowledge_count: int,
        question_count: int,
    ) -> tuple:
        return content_yield_check(
            document=document,
            latest_run=latest_run,
            knowledge_count=knowledge_count,
            question_count=question_count,
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
        add_check(
            checks,
            key=key,
            label=label,
            status=status,
            message=message,
        )

    @staticmethod
    def _overall_status(
        checks: Sequence[Dict[str, Any]],
        latest_run: Optional[EntityExtractionRun],
        questions: Sequence[Question],
        knowledge_points: Sequence[KnowledgePoint],
    ) -> str:
        return overall_status(checks, latest_run, questions, knowledge_points)

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
        return quality_score(
            status=status,
            content_yield_failed=content_yield_failed,
            unresolved_question_count=unresolved_question_count,
            skipped_question_count=skipped_question_count,
            unassigned_question_count=unassigned_question_count,
            ungrouped_count=ungrouped_count,
            numbering_issue_count=numbering_issue_count,
            ai_generated_option_count=ai_generated_option_count,
        )

    @staticmethod
    def _status_label(status: str) -> str:
        return status_label(status)

    @staticmethod
    def _status_summary(status: str, fail_count: int, warning_count: int) -> str:
        return status_summary(status, fail_count, warning_count)

    @staticmethod
    def _serialize_latest_run(
        latest_run: Optional[EntityExtractionRun],
    ) -> Optional[Dict[str, Any]]:
        return serialize_latest_run(latest_run)

    @staticmethod
    def _as_non_negative_int(value: Any) -> int:
        return as_non_negative_int(value)
