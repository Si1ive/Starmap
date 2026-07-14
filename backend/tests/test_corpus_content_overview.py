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
    assert gate["issues"] == []


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
        extraction_meta={
            "fixed_by_llm": True,
            "original_issues": [{"issue_type": "too_few"}],
        },
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
    assert {
        issue["key"] for issue in gate["issues"]
    } == {
        "ai-generated-option:q1",
        "question-unassigned:q1",
    }
    generated_issue = next(
        issue
        for issue in gate["issues"]
        if issue["key"] == "ai-generated-option:q1"
    )
    assert generated_issue["entity_label"] == "第1题"
    assert generated_issue["message"] == "选项 D 由 AI 生成，需要对照原卷核验"


def test_quality_gate_blocks_unresolved_and_unsaved_questions():
    diagnostic = {
        "skipped_question_count": 1,
        "unsaved_samples": [
            {
                "question_no": 8,
                "page_no": 2,
                "reason": "save_failed",
                "text_excerpt": "测试未落库题目",
            }
        ],
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
    structure_issue = next(
        issue
        for issue in gate["issues"]
        if issue["key"] == "question-structure:q1"
    )
    assert structure_issue["entity_label"] == "第1题"
    assert structure_issue["message"] == "仅识别到选项 A、B、C，缺少 D"
    unsaved_issue = next(
        issue
        for issue in gate["issues"]
        if issue["key"] == "question-unsaved:0"
    )
    assert unsaved_issue["entity_label"] == "第8题"
    assert unsaved_issue["message"] == (
        "未成功入库：数据库保存失败；题干：测试未落库题目"
    )


def test_quality_gate_identifies_duplicate_question_numbers():
    gate = CorpusContentOverviewService.build_quality_gate(
        document=_document(),
        knowledge_points=[],
        questions=[
            _question(question_id="q1", number="30"),
            _question(question_id="q2", number="30"),
        ],
        summary=_summary(question_count=2),
        latest_run=_run(),
    )

    duplicate_issue = next(
        issue
        for issue in gate["issues"]
        if issue["key"] == "question-number-duplicate:30"
    )
    assert gate["status"] == "warning"
    assert duplicate_issue["entity_id"] == "q1"
    assert duplicate_issue["entity_label"] == "第30题"
    assert duplicate_issue["message"] == "该题号共出现 2 次，需要确认是否错误拆题"


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


def test_content_overview_keeps_latest_run_per_entity_target():
    newest = SimpleNamespace(
        id="run-new",
        status="success",
        scope="entity",
        target_entity_type="question",
        target_entity_id="question-1",
        error_detail=None,
        result_json={"question_count": 1},
        started_at=datetime(2026, 7, 14, 11, 0, 0),
        completed_at=datetime(2026, 7, 14, 11, 1, 0),
    )
    older = SimpleNamespace(
        id="run-old",
        status="failed",
        scope="entity",
        target_entity_type="question",
        target_entity_id="question-1",
        error_detail="old failure",
        result_json=None,
        started_at=datetime(2026, 7, 14, 10, 0, 0),
        completed_at=datetime(2026, 7, 14, 10, 1, 0),
    )

    result = CorpusContentOverviewService.build_latest_entity_run_map(
        [newest, older]
    )

    assert result[("question", "question-1")]["id"] == "run-new"
    assert result[("question", "question-1")]["status"] == "success"
