"""Diagnostic summaries for the question extraction pipeline."""

from collections import Counter
from typing import Any, Dict, List

from app.modules.corpus.question_validation import extract_question_number


def build_question_extraction_diagnostic(
    raw_questions: List[Dict[str, Any]],
    final_questions: List[Dict[str, Any]],
    validation_report: Dict[str, Any],
    final_report: Dict[str, Any],
    saved_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the extraction summary returned to corpus management clients."""
    save_reasons = Counter(item.get("reason") or "unknown" for item in saved_results)
    saved_question_count = sum(1 for item in saved_results if item.get("saved"))
    raw_by_page = Counter(
        question.get("page_no")
        for question in raw_questions
        if question.get("page_no") is not None
    )
    final_by_page = Counter(
        question.get("page_no")
        for question in final_questions
        if question.get("page_no") is not None
    )
    saved_by_page = Counter(
        item.get("page_no")
        for item in saved_results
        if item.get("saved") and item.get("page_no") is not None
    )
    skipped_by_page = Counter(
        item.get("page_no")
        for item in saved_results
        if not item.get("saved") and item.get("page_no") is not None
    )
    page_numbers = sorted(
        set(raw_by_page) | set(final_by_page) | set(saved_by_page) | set(skipped_by_page)
    )

    return {
        "raw_question_count": len(raw_questions),
        "final_question_count": len(final_questions),
        "saved_question_count": saved_question_count,
        "skipped_question_count": len(saved_results) - saved_question_count,
        "save_reasons": dict(save_reasons),
        "by_page": [
            {
                "page_no": page_no,
                "raw_question_count": raw_by_page.get(page_no, 0),
                "final_question_count": final_by_page.get(page_no, 0),
                "saved_question_count": saved_by_page.get(page_no, 0),
                "skipped_question_count": skipped_by_page.get(page_no, 0),
            }
            for page_no in page_numbers
        ],
        "numbering": question_numbering_summary(final_questions, final_report),
        "validation": {
            "initial_issue_count": validation_report.get("summary", {}).get(
                "total_issues", 0
            ),
            "final_issue_count": final_report.get("summary", {}).get(
                "total_issues", 0
            ),
            "initial_critical_issue_count": len(
                validation_report.get("summary", {}).get("critical_issues", [])
            ),
            "final_critical_issue_count": len(
                final_report.get("summary", {}).get("critical_issues", [])
            ),
        },
        "unsaved_samples": [
            item for item in saved_results if not item.get("saved")
        ][:20],
    }


def question_numbering_summary(
    questions: List[Dict[str, Any]],
    final_report: Dict[str, Any],
) -> Dict[str, Any]:
    """Summarize extracted question numbering and continuity."""
    numbers = [
        number
        for number in (extract_question_number(question) for question in questions)
        if number is not None
    ]
    duplicate_numbers = [
        number for number, count in Counter(numbers).items() if count > 1
    ]
    max_number = max(numbers, default=0)
    number_set = set(numbers)
    missing_numbers = (
        [
            number
            for number in range(min(numbers), max_number + 1)
            if number not in number_set
        ]
        if numbers
        else []
    )

    continuity = final_report.get("number_continuity", {})
    return {
        "numbered_question_count": len(numbers),
        "unnumbered_question_count": len(questions) - len(numbers),
        "min_number": min(numbers) if numbers else None,
        "max_number": max_number or None,
        "missing_numbers": missing_numbers,
        "duplicate_numbers": sorted(duplicate_numbers),
        "segment_count": len(continuity.get("segments", [])),
    }


def question_text_excerpt(
    question_dict: Dict[str, Any],
    limit: int = 120,
) -> str:
    """Return a compact, whitespace-normalized question excerpt."""
    text = " ".join(
        (
            question_dict.get("stem")
            or question_dict.get("content")
            or question_dict.get("raw_text")
            or ""
        ).split()
    )
    return text if len(text) <= limit else f"{text[:limit]}..."


def extract_fix_history(
    questions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collect deterministic and LLM repair actions for diagnostics."""
    history = []
    for index, question in enumerate(questions):
        if question.get("fixed_by_rule"):
            history.append(
                {
                    "question_index": index,
                    "question_id": question.get("id"),
                    "fix_type": "rule",
                    "fix_action": question.get("fixed_by_rule"),
                    "details": {
                        "source_index": question.get("fixed_source_index"),
                        "inferred_number": question.get("inferred_number"),
                    },
                }
            )
        if question.get("fixed_by_llm"):
            llm_actions = (
                (question.get("extraction_meta") or {}).get("llm_fix_actions")
                or question.get("llm_fix_actions")
                or []
            )
            history.append(
                {
                    "question_index": index,
                    "question_id": question.get("id"),
                    "fix_type": "llm",
                    "fix_action": (
                        llm_actions[-1].get("action")
                        if llm_actions and isinstance(llm_actions[-1], dict)
                        else "llm_fix"
                    ),
                    "details": llm_actions,
                }
            )
    return history
