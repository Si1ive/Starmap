"""Document section chapter matching rule tests."""

from types import SimpleNamespace

import pytest

from app.modules.catalog.section_mapping_rules import (
    build_chapter_index,
    match_section,
    match_section_multi,
)


def make_chapter(
    chapter_id: str,
    name: str,
    *,
    aliases=None,
    code=None,
    level=1,
):
    return SimpleNamespace(
        id=chapter_id,
        name=name,
        aliases=aliases or [],
        code=code,
        level=level,
    )


def make_section(title: str, section_path: str = ""):
    return SimpleNamespace(title=title, section_path=section_path)


def test_build_chapter_index_preserves_name_over_alias_and_code():
    chapters = [
        make_chapter(
            "chapter-main",
            "进程管理",
            aliases=["进程"],
            code="OS-1",
            level=2,
        ),
        make_chapter(
            "chapter-other",
            "进程",
            aliases=["OS-1"],
            code="OTHER",
        ),
    ]

    index = build_chapter_index(chapters)

    assert index["进程管理"] == {
        "id": "chapter-main",
        "level": 2,
        "match_type": "exact",
    }
    assert index["进程"]["id"] == "chapter-other"
    assert index["进程"]["match_type"] == "exact"
    assert index["os-1"]["id"] == "chapter-main"
    assert index["os-1"]["match_type"] == "code"


def test_match_section_prefers_exact_title():
    index = build_chapter_index(
        [make_chapter("chapter-1", "进程管理", aliases=["进程"])]
    )

    result = match_section(make_section(" 进程管理 "), index)

    assert result == ("chapter-1", 1.0, "exact")


def test_match_section_uses_section_path_before_title_contains():
    index = build_chapter_index(
        [
            make_chapter("chapter-path", "操作系统"),
            make_chapter("chapter-title", "进程管理"),
        ]
    )

    result = match_section(
        make_section("进程管理基础", "计算机基础 > 操作系统"),
        index,
    )

    assert result == ("chapter-path", 0.85, "partial")


def test_match_section_selects_strongest_containment_match():
    index = build_chapter_index(
        [
            make_chapter("chapter-short", "管理"),
            make_chapter("chapter-long", "进程管理"),
        ]
    )

    result = match_section(make_section("操作系统进程管理"), index)

    assert result is not None
    assert result[0] == "chapter-long"
    assert result[2] == "partial"
    assert result[1] == pytest.approx(0.8)


def test_match_section_supports_related_word_overlap():
    index = build_chapter_index(
        [make_chapter("chapter-1", "data structure linear table")]
    )

    result = match_section(
        make_section("linear table implementation"),
        index,
    )

    assert result == ("chapter-1", 0.65, "related")


def test_match_section_multi_selects_highest_confidence_across_subjects():
    chapter_indices = {
        "subject-1": build_chapter_index(
            [make_chapter("chapter-partial", "进程管理")]
        ),
        "subject-2": build_chapter_index(
            [make_chapter("chapter-exact", "操作系统进程管理")]
        ),
    }

    result = match_section_multi(
        make_section("操作系统进程管理"),
        chapter_indices,
    )

    assert result == ("chapter-exact", 1.0, "exact")


def test_match_section_returns_none_without_reliable_signal():
    index = build_chapter_index(
        [make_chapter("chapter-1", "进程管理")]
    )

    assert match_section(make_section("数据库索引"), index) is None
