"""语料实体入库前纯内容规则测试。"""

from types import SimpleNamespace

from app.modules.corpus.entity_content_rules import (
    build_knowledge_content,
    extract_answers_from_blocks,
    extract_topic_terms,
    normalize_options,
    strip_leading_option_marker,
)


def test_strip_leading_option_marker_handles_mineru_subscript_noise() -> None:
    assert (
        strip_leading_option_marker(
            "A。选项正文",
            expected_label="A",
        )
        == "选项正文"
    )
    assert (
        strip_leading_option_marker(
            "<sub>。</sub>选项正文",
            expected_label="B",
        )
        == "选项正文"
    )


def test_normalize_options_deduplicates_and_preserves_source() -> None:
    options = normalize_options(
        [
            {
                "key": "A",
                "text": "A。原文选项",
                "source": "extracted",
            },
            {"label": "A", "text": "重复选项"},
            {
                "option_label": "B",
                "content": "AI 补充选项",
                "source": "ai_generated",
            },
            {"key": "C", "text": ""},
        ]
    )

    assert [option["key"] for option in options] == ["A", "B"]
    assert options[0]["text"] == "原文选项"
    assert options[0]["source"] == "extracted"
    assert options[1]["source"] == "ai_generated"


def test_extract_topic_terms_reads_title_and_quoted_terms() -> None:
    terms = extract_topic_terms(
        "第 3 章 进程管理",
        "重点理解“进程同步”和「死锁检测」。",
    )

    assert {"进程管理", "进程同步", "死锁检测"} <= set(terms)


def test_build_knowledge_content_prefers_markdown() -> None:
    blocks = [
        SimpleNamespace(
            content_md="第一段 **正文**",
            content_text="第一段正文",
        ),
        SimpleNamespace(content_md="", content_text="第二段正文"),
        SimpleNamespace(content_md=None, content_text="  "),
    ]

    assert build_knowledge_content(blocks) == ("第一段 **正文**\n\n第二段正文")


def test_extract_answers_requires_answer_zone() -> None:
    blocks = [
        SimpleNamespace(
            content_text="1. A 是题干内容",
            content_md=None,
        ),
        SimpleNamespace(
            content_text="参考答案 1.B 2、CD",
            content_md=None,
        ),
        SimpleNamespace(
            content_text="3：对 4) 错",
            content_md=None,
        ),
    ]

    assert extract_answers_from_blocks(blocks) == {
        "1": "B",
        "2": "CD",
        "3": "对",
        "4": "错",
    }
    assert extract_answers_from_blocks(blocks[:1]) == {}
