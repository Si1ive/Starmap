from app.modules.catalog.outline_segmentation import (
    segment_outline_subjects,
    split_outline_chapter_chunks,
)


def test_segment_outline_subjects_uses_first_alias_for_each_subject():
    markdown = (
        "前言\n"
        "数据结构\n第一章 线性表\n"
        "计算机组成原理\n第一章 计算机系统概述\n"
        "后文再次提到计组和数据结构\n"
        "操作系统\n第一章 进程管理"
    )

    segments = segment_outline_subjects(markdown)

    assert [segment[0] for segment in segments] == [
        "data_structure",
        "computer_organization",
        "operating_system",
    ]
    assert [markdown[start:end].splitlines()[0] for _, start, end in segments] == [
        "数据结构",
        "计算机组成原理",
        "操作系统",
    ]
    assert segments[-1][2] == len(markdown)


def test_segment_outline_subjects_requires_at_least_two_subjects():
    assert segment_outline_subjects("数据结构\n第一章 线性表") == []
    assert segment_outline_subjects("没有标准科目名称") == []


def test_segment_outline_subjects_supports_short_aliases():
    markdown = "计组\n处理器\n计网\n网络体系结构"

    segments = segment_outline_subjects(markdown)

    assert [segment[0] for segment in segments] == [
        "computer_organization",
        "computer_network",
    ]


def test_split_outline_chapter_chunks_starts_new_block_at_heading():
    content = "第一章\nabcdefgh\n第二章\nxyz"

    chunks = split_outline_chapter_chunks(content, max_chunk_size=10)

    assert chunks == ["第一章\nabcdefgh", "第二章\nxyz"]


def test_split_outline_chapter_chunks_supports_chinese_and_numeric_headings():
    content = "说明文字很长\n一、数据结构\n内容\n2. 操作系统\n内容"

    chunks = split_outline_chapter_chunks(content, max_chunk_size=5)

    assert chunks == ["说明文字很长", "一、数据结构\n内容", "2. 操作系统\n内容"]


def test_split_outline_chapter_chunks_does_not_cut_without_heading():
    content = "普通内容\n" + ("x" * 50)

    assert split_outline_chapter_chunks(content, max_chunk_size=5) == [content]
