"""Pure rules used to build corpus ingestion quality reports."""

from typing import Any, Dict, List, Optional, Sequence

EXPECTED_OPTION_LABELS = ("A", "B", "C", "D")


def is_question_unassigned(question: Any) -> bool:
    return not question.subject_id or not question.chapter_id


def join_labels(labels: Sequence[str]) -> str:
    return "、".join(dict.fromkeys(label for label in labels if label))


def question_integrity_message(
    *,
    question: Any,
    options: Sequence[Dict[str, Any]],
    meta: Dict[str, Any],
    expected_option_labels: Sequence[str] = EXPECTED_OPTION_LABELS,
) -> str:
    reasons = []
    if question.type == "choice" and len(options) < 4:
        labels = {
            str(
                option.get("key")
                or option.get("label")
                or option.get("option_label")
                or ""
            )
            .strip()
            .upper()[:1]
            for option in options
        }
        labels.discard("")
        missing_labels = [
            label for label in expected_option_labels if label not in labels
        ]
        if labels and missing_labels:
            reasons.append(
                f"仅识别到选项 {join_labels(sorted(labels))}，"
                f"缺少 {join_labels(missing_labels)}"
            )
        else:
            reasons.append(f"选择题仅识别到 {len(options)} 个选项，选项结构不完整")
    if meta.get("suspected_truncated_options"):
        reasons.append("存在疑似被截断的选项文本")
    return "；".join(reasons) or "题目存在未解决的关键结构问题"


def question_label(question: Any) -> str:
    number = str(getattr(question, "question_no", "") or "").strip()
    if number:
        return f"第{number}题"
    content = str(getattr(question, "content", "") or "").strip()
    excerpt = content[:18] + ("..." if len(content) > 18 else "")
    return f"无题号题目：{excerpt}" if excerpt else "无题号题目"


def unsaved_question_label(sample: Dict[str, Any]) -> str:
    number = sample.get("question_no")
    if number is not None:
        return f"第{number}题"
    page_no = sample.get("page_no")
    return f"第{page_no}页题目" if page_no is not None else "未落库题目"


def unsaved_question_message(sample: Dict[str, Any]) -> str:
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


def add_issue(
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


def content_yield_check(
    *,
    document: Any,
    latest_run: Optional[Any],
    knowledge_count: int,
    question_count: int,
) -> tuple[str, str]:
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


def add_check(
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


def overall_status(
    checks: Sequence[Dict[str, Any]],
    latest_run: Optional[Any],
    questions: Sequence[Any],
    knowledge_points: Sequence[Any],
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


def quality_score(
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


def status_label(status: str) -> str:
    return {
        "passed": "质量通过",
        "warning": "建议核验",
        "blocked": "需要修复",
        "running": "评估中",
        "failed": "抽取失败",
        "not_run": "尚未抽取",
    }[status]


def status_summary(status: str, fail_count: int, warning_count: int) -> str:
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


def serialize_latest_run(latest_run: Optional[Any]) -> Optional[Dict[str, Any]]:
    if not latest_run:
        return None
    return {
        "id": latest_run.id,
        "status": latest_run.status,
        "knowledge_count": latest_run.knowledge_count or 0,
        "question_count": latest_run.question_count or 0,
        "error_detail": latest_run.error_detail,
        "started_at": (
            latest_run.started_at.isoformat() if latest_run.started_at else None
        ),
        "completed_at": (
            latest_run.completed_at.isoformat() if latest_run.completed_at else None
        ),
    }


def as_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
