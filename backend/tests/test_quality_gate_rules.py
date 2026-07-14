from datetime import datetime
from types import SimpleNamespace

from app.modules.corpus.quality_gate_rules import (
    add_check,
    add_issue,
    as_non_negative_int,
    content_yield_check,
    overall_status,
    quality_score,
    question_integrity_message,
    question_label,
    serialize_latest_run,
    status_summary,
    unsaved_question_message,
)


def test_question_integrity_message_lists_missing_choice_labels():
    question = SimpleNamespace(type="choice")

    message = question_integrity_message(
        question=question,
        options=[
            {"key": "A", "text": "A"},
            {"key": "B", "text": "B"},
            {"key": "D", "text": "D"},
        ],
        meta={"suspected_truncated_options": True},
    )

    assert message == "仅识别到选项 A、B、D，缺少 C；存在疑似被截断的选项文本"


def test_quality_gate_entity_messages_are_specific_and_traceable():
    question = SimpleNamespace(question_no=None, content="一段用于定位的无题号题干内容")
    sample = {
        "reason": "missing_chapter",
        "text_excerpt": "未成功入库的题干",
    }

    assert question_label(question) == "无题号题目：一段用于定位的无题号题干内容"
    assert unsaved_question_message(sample) == (
        "未成功入库：缺少章节归属；题干：未成功入库的题干"
    )


def test_quality_gate_collection_helpers_keep_response_contract():
    checks = []
    issues = []

    add_check(
        checks,
        key="question_integrity",
        label="题目完整性",
        status="fail",
        message="存在结构问题",
    )
    add_issue(
        issues,
        key="question-structure:q1",
        check_key="question_integrity",
        severity="fail",
        entity_type="question",
        entity_id="q1",
        entity_label="第1题",
        message="缺少 D",
    )

    assert checks == [
        {
            "key": "question_integrity",
            "label": "题目完整性",
            "status": "fail",
            "message": "存在结构问题",
        }
    ]
    assert issues == [
        {
            "key": "question-structure:q1",
            "check_key": "question_integrity",
            "severity": "fail",
            "entity_type": "question",
            "entity_id": "q1",
            "entity_label": "第1题",
            "message": "缺少 D",
        }
    ]


def test_quality_gate_status_and_score_rules_are_independent_of_orm():
    checks = [{"status": "warning"}]

    status = overall_status(checks, None, [object()], [])
    score = quality_score(
        status=status,
        content_yield_failed=False,
        unresolved_question_count=1,
        skipped_question_count=1,
        unassigned_question_count=1,
        ungrouped_count=1,
        numbering_issue_count=1,
        ai_generated_option_count=1,
    )

    assert status == "warning"
    assert score == 63
    assert status_summary(status, 0, 2) == ("没有阻断问题，但有 2 项需要人工关注。")


def test_content_yield_and_run_serialization_rules():
    document = SimpleNamespace(doc_type="past_exam")
    latest_run = SimpleNamespace(
        id="run-1",
        status="success",
        knowledge_count=None,
        question_count=2,
        error_detail=None,
        started_at=datetime(2026, 7, 14, 10, 0, 0),
        completed_at=None,
    )

    assert content_yield_check(
        document=document,
        latest_run=latest_run,
        knowledge_count=0,
        question_count=0,
    ) == ("fail", "试卷类文档没有产出题目")
    assert serialize_latest_run(latest_run) == {
        "id": "run-1",
        "status": "success",
        "knowledge_count": 0,
        "question_count": 2,
        "error_detail": None,
        "started_at": "2026-07-14T10:00:00",
        "completed_at": None,
    }
    assert as_non_negative_int("-3") == 0
    assert as_non_negative_int("invalid") == 0
