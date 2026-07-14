"""Document section extraction and heading rule tests."""

from app.modules.corpus.document_section_service import DocumentSectionService
from app.modules.corpus.section_heading import (
    build_section_path,
    detect_heading_level,
    looks_like_question_or_option,
)
def test_heading_rules_detect_native_section_levels():
    assert detect_heading_level("第1章 操作系统概述", "heading") == 1
    assert detect_heading_level("第2节 进程管理", "paragraph") == 2
    assert detect_heading_level("1.2.3 进程同步", "paragraph") == 3


def test_heading_rules_reject_question_and_option_content():
    subjective_question = (
        "43 （12 分） 假设有两个整数 x 和 y，采用补码形式表示，"
        "请回答下列问题"
    )

    assert looks_like_question_or_option(subjective_question)
    assert detect_heading_level(subjective_question, "heading") is None
    assert detect_heading_level("A. 寄存器 A 中的内容", "heading") is None


def test_build_section_path_uses_open_parent_chain():
    sections = [
        {"level": 1, "title": "第1章 操作系统概述"},
        {"level": 2, "title": "第1节 基本概念"},
    ]

    assert build_section_path(
        sections,
        3,
        "1.1.1 操作系统目标",
    ) == "第1章 操作系统概述 > 第1节 基本概念 > 1.1.1 操作系统目标"
