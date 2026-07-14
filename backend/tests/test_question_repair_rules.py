"""题目 LLM 修复来源与安全替换规则测试。"""

from types import SimpleNamespace

from app.modules.corpus.question_repair_rules import (
    collect_context_source_text,
    collect_target_source_text,
    is_safe_option_replacement,
    is_safe_repaired_stem,
    normalize_source_text,
    text_exists_in_source,
)


def test_collect_target_source_text_supports_dict_and_object_blocks() -> None:
    question = {
        "raw_text": "原始题干",
        "stem": "当前题干",
        "blocks": [
            {"content_text": "字典块"},
            SimpleNamespace(
                content_text=None,
                content_md="对象块",
            ),
        ],
    }

    source_text = collect_target_source_text(question)

    assert "原始题干" in source_text
    assert "当前题干" in source_text
    assert "字典块" in source_text
    assert "对象块" in source_text


def test_collect_context_source_text_uses_previous_target_next_only() -> None:
    questions = [
        {
            "raw_text": f"题目 {number}",
            "options": [{"text": f"选项 {number}"}],
        }
        for number in range(1, 6)
    ]

    source_text = collect_context_source_text(questions, 2)

    assert "题目 2" in source_text
    assert "题目 3" in source_text
    assert "题目 4" in source_text
    assert "题目 1" not in source_text
    assert "题目 5" not in source_text


def test_source_text_comparison_ignores_whitespace() -> None:
    assert normalize_source_text("A \n B　C") == "ABC"
    assert text_exists_in_source(
        "(rear-length+m) MOD m",
        "B (rear-length+m)\nMOD m C",
    )


def test_repaired_stem_can_only_remove_existing_suffix() -> None:
    current = "30。题干。A 被粘入题干的选项"

    assert is_safe_repaired_stem(current, "30。题干。") is True
    assert is_safe_repaired_stem(current, "30。改写后的题干。") is False


def test_option_replacement_requires_longer_source_backed_text() -> None:
    source = "D (rear+length-1) MOD m"

    assert is_safe_option_replacement(
        "m",
        "(rear+length-1) MOD m",
        source,
    )
    assert not is_safe_option_replacement(
        "m",
        "LLM 生成的完整选项",
        source,
    )
    assert not is_safe_option_replacement(
        "(rear+length-1) MOD m",
        "m",
        source,
    )
