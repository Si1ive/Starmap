from app.services.entity_extraction_service import OptionIntegrityChecker


def test_option_integrity_accepts_key_field():
    checker = OptionIntegrityChecker()

    result = checker.check({
        "question_type": "choice",
        "options": [
            {"key": "A", "text": "选项一"},
            {"key": "B", "text": "选项二"},
            {"key": "C", "text": "选项三"},
            {"key": "D", "text": "选项四"},
        ],
    })

    assert result["is_complete"] is True
