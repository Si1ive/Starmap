from app.modules.corpus.question_number_rules import (
    QuestionNumberChecker,
    extract_question_number,
    parse_question_number,
)
from app.modules.corpus.question_validation import (
    QuestionNumberChecker as CompatibilityQuestionNumberChecker,
)
from app.modules.corpus.question_validation import (
    extract_question_number as compatibility_extract_question_number,
)


def test_question_number_patterns_cover_supported_formats():
    assert parse_question_number("12. 题干") == 12
    assert parse_question_number("（3）题干") == 3
    assert parse_question_number("[7] 题干") == 7
    assert parse_question_number("例4题干") == 4
    assert parse_question_number("第9题 题干") == 9
    assert parse_question_number("没有题号") is None


def test_extract_question_number_preserves_public_stem_content_contract():
    assert extract_question_number({"stem": "5、题干"}) == 5
    assert extract_question_number({"content": "6 题干"}) == 6
    assert extract_question_number({"raw_text": "7. 题干"}) is None


def test_question_number_checker_detects_gaps_duplicates_and_unnumbered_items():
    checker = QuestionNumberChecker()
    questions = [
        {"stem": "1. 第一题"},
        {"stem": "2. 第二题"},
        {"stem": "4. 第四题"},
        {"stem": "4. 重复第四题"},
        {"stem": "无题号题目"},
    ]

    number_infos = checker.extract_question_numbers(questions)
    report = checker.detect_continuity_issues(number_infos)
    issues = report["segments"][0]["issues"]

    assert report["global_issues"] == {
        "total_questions": 5,
        "numbered_questions": 4,
        "unnumbered_questions": 1,
        "unnumbered_indices": [4],
    }
    assert {
        (issue["type"], issue.get("missing_number"), issue.get("number"))
        for issue in issues
    } >= {
        ("missing", 3, None),
        ("duplicate", None, 4),
    }
    assert any(
        issue["type"] == "jump"
        and issue["from_number"] == 2
        and issue["to_number"] == 4
        for issue in issues
    )


def test_question_number_checker_splits_pattern_and_restart_segments():
    checker = QuestionNumberChecker()
    number_infos = checker.extract_question_numbers(
        [
            {"stem": "1. 第一组第一题"},
            {"stem": "2. 第一组第二题"},
            {"stem": "1. 第二组第一题"},
            {"stem": "（1）第三组第一题"},
        ]
    )

    report = checker.detect_continuity_issues(number_infos)

    assert [segment["numbers"] for segment in report["segments"]] == [
        [1, 2],
        [1],
        [1],
    ]
    assert [segment["pattern"] for segment in report["segments"]] == [
        "arabic",
        "arabic",
        "paren",
    ]


def test_question_validation_keeps_legacy_number_rule_exports():
    assert CompatibilityQuestionNumberChecker is QuestionNumberChecker
    assert compatibility_extract_question_number is extract_question_number
