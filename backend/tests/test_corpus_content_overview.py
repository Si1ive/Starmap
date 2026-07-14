from datetime import datetime
from types import SimpleNamespace

from app.modules.corpus.content_overview import CorpusContentOverviewService


def _document(doc_type="past_exam"):
    return SimpleNamespace(id="doc-1", doc_type=doc_type)


def _question(
    question_id="q1",
    *,
    number="1",
    options=None,
    subject_id="subject-1",
    chapter_id="chapter-1",
    extraction_meta=None,
):
    return SimpleNamespace(
        id=question_id,
        type="choice",
        question_no=number,
        options=options or [
            {"key": "A", "text": "A"},
            {"key": "B", "text": "B"},
            {"key": "C", "text": "C"},
            {"key": "D", "text": "D"},
        ],
        subject_id=subject_id,
        chapter_id=chapter_id,
        extraction_meta=extraction_meta or {},
    )


def _run(*, status="success", diagnostic=None):
    return SimpleNamespace(
        id="run-1",
        status=status,
        result_json={"question_diagnostic": diagnostic or {}},
        knowledge_count=0,
        question_count=1,
        error_detail=None,
        started_at=datetime(2026, 7, 14, 10, 0, 0),
        completed_at=datetime(2026, 7, 14, 10, 1, 0),
    )


def _summary(**overrides):
    result = {
        "knowledge_count": 0,
        "question_count": 1,
        "chapter_count": 1,
        "ungrouped_count": 0,
        "unassigned_question_count": 0,
    }
    result.update(overrides)
    return result


def test_quality_gate_passes_clean_exam_content():
    gate = CorpusContentOverviewService.build_quality_gate(
        document=_document(),
        knowledge_points=[],
        questions=[_question()],
        summary=_summary(),
        latest_run=_run(),
    )

    assert gate["status"] == "passed"
    assert gate["score"] == 100
    assert gate["manual_review_required"] is False
    assert all(check["status"] == "pass" for check in gate["checks"])


def test_quality_gate_warns_for_generated_option_and_missing_assignment():
    question = _question(
        subject_id=None,
        chapter_id=None,
        options=[
            {"key": "A", "text": "A"},
            {"key": "B", "text": "B"},
            {"key": "C", "text": "C"},
            {"key": "D", "text": "D", "source": "ai_generated"},
        ],
        extraction_meta={"fixed_by_llm": True, "original_issues": [{"issue_type": "too_few"}]},
    )

    gate = CorpusContentOverviewService.build_quality_gate(
        document=_document(),
        knowledge_points=[],
        questions=[question],
        summary=_summary(unassigned_question_count=1),
        latest_run=_run(),
    )

    assert gate["status"] == "warning"
    assert gate["manual_review_required"] is True
    assert gate["metrics"]["ai_generated_option_count"] == 1
    assert gate["metrics"]["llm_repaired_question_count"] == 1
    assert gate["metrics"]["original_issue_question_count"] == 1


def test_quality_gate_blocks_unresolved_and_unsaved_questions():
    diagnostic = {
        "skipped_question_count": 1,
        "validation": {
            "initial_issue_count": 3,
            "final_issue_count": 1,
            "final_critical_issue_count": 1,
        },
    }
    question = _question(
        options=[
            {"key": "A", "text": "A"},
            {"key": "B", "text": "B"},
            {"key": "C", "text": "C"},
        ],
        extraction_meta={"few_options": True},
    )

    gate = CorpusContentOverviewService.build_quality_gate(
        document=_document(),
        knowledge_points=[],
        questions=[question],
        summary=_summary(),
        latest_run=_run(diagnostic=diagnostic),
    )

    assert gate["status"] == "blocked"
    assert gate["metrics"]["unresolved_question_count"] == 1
    assert gate["metrics"]["skipped_question_count"] == 1
    assert gate["score"] == 75
    assert {
        check["key"]
        for check in gate["checks"]
        if check["status"] == "fail"
    } == {"question_integrity", "save_integrity"}


def test_quality_gate_blocks_exam_without_questions():
    gate = CorpusContentOverviewService.build_quality_gate(
        document=_document(),
        knowledge_points=[],
        questions=[],
        summary=_summary(question_count=0, chapter_count=0),
        latest_run=_run(),
    )

    assert gate["status"] == "blocked"
    content_check = next(
        check for check in gate["checks"] if check["key"] == "content_yield"
    )
    assert content_check["status"] == "fail"
    assert gate["score"] == 60
