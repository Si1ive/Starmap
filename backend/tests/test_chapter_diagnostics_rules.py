from types import SimpleNamespace

from app.modules.catalog.chapter_diagnostics_rules import (
    block_issues,
    build_section_range,
    diagnostic_status,
    looks_like_option_block,
    looks_like_question_start,
    ownership_issues,
    page_issues,
    resolve_page_mapping,
    section_for_block,
    section_for_page,
    select_mapping_for_section,
)


def _section(
    section_id: str,
    *,
    level: int,
    page_start: int,
    page_end: int,
    block_start_id: str,
    block_end_id: str,
):
    return SimpleNamespace(
        id=section_id,
        level=level,
        page_start=page_start,
        page_end=page_end,
        block_start_id=block_start_id,
        block_end_id=block_end_id,
    )


def _mapping(mapping_id: str, status: str, confidence: float):
    return (
        SimpleNamespace(
            id=mapping_id,
            review_status=status,
            confidence=confidence,
        ),
        SimpleNamespace(id=f"chapter-{mapping_id}"),
        SimpleNamespace(id=f"subject-{mapping_id}"),
    )


def test_question_and_option_signals_are_mutually_exclusive():
    assert looks_like_question_start(
        "43 假设有两个整数 x 和 y，请回答下列问题",
        "paragraph",
    )
    assert looks_like_question_start("第十二题 说明算法思想", "heading")
    assert looks_like_option_block("A. 寄存器内容")
    assert not looks_like_question_start("A. 寄存器内容", "paragraph")
    assert not looks_like_question_start("43 普通目录项", "table")


def test_section_selection_prefers_deepest_matching_range():
    root = _section(
        "root",
        level=1,
        page_start=1,
        page_end=3,
        block_start_id="b1",
        block_end_id="b4",
    )
    child = _section(
        "child",
        level=2,
        page_start=2,
        page_end=2,
        block_start_id="b2",
        block_end_id="b3",
    )
    block_index = {"b1": 0, "b2": 1, "b3": 2, "b4": 3}
    ranges = [
        build_section_range(root, block_index, 4),
        build_section_range(child, block_index, 4),
    ]
    block = SimpleNamespace(id="b2", page_no=2)

    assert section_for_page(2, ranges)["section"].id == "child"
    assert section_for_block(block, block_index, ranges)["section"].id == "child"
    assert section_for_page(4, ranges) is None


def test_mapping_selection_prefers_accepted_status_before_confidence():
    rejected = _mapping("rejected", "rejected", 0.99)
    pending = _mapping("pending", "pending", 0.70)
    approved = _mapping("approved", "approved", 0.90)
    mappings = {"section-1": [rejected, pending, approved]}

    selected = select_mapping_for_section("section-1", mappings)
    accepted = select_mapping_for_section(
        "section-1",
        mappings,
        accepted_only=True,
    )

    assert selected[0].id == "approved"
    assert accepted[0].id == "approved"
    assert select_mapping_for_section(
        "section-2",
        {"section-2": [rejected]},
        accepted_only=True,
    ) is None


def test_page_mapping_prefers_exact_then_previous_then_next():
    mappings = {
        2: {"canonical_chapter_id": "chapter-2"},
        8: {"canonical_chapter_id": "chapter-8"},
    }

    exact = resolve_page_mapping(2, mappings)
    previous = resolve_page_mapping(6, mappings)
    next_mapping = resolve_page_mapping(1, mappings)

    assert exact["source"] == "section_range"
    assert exact["fallback_distance"] == 0
    assert previous["canonical_chapter_id"] == "chapter-2"
    assert previous["source"] == "previous_page"
    assert previous["fallback_distance"] == 4
    assert next_mapping["canonical_chapter_id"] == "chapter-2"
    assert next_mapping["source"] == "next_page"
    assert next_mapping["fallback_distance"] == 1


def test_exam_documents_use_explicit_mapping_issue_levels():
    page_result = page_issues(None, None, None, is_exam_doc=True)
    block_result = block_issues(None, None, None, is_exam_doc=True)

    assert page_result[0]["code"] == "exam_no_chapter_mapping"
    assert page_result[0]["severity"] == "error"
    assert block_result[0]["code"] == "exam_no_chapter_mapping"
    assert block_result[0]["severity"] == "warning"


def test_ownership_issues_report_neighbor_fallback_and_mismatch():
    section_mapping = {
        "review_status": "approved",
        "canonical_chapter_id": "chapter-native",
    }
    extraction_mapping = {
        "source": "previous_page",
        "canonical_chapter_id": "chapter-fallback",
    }

    issues = ownership_issues(section_mapping, extraction_mapping)

    assert [issue["code"] for issue in issues] == [
        "extraction_mapping_from_neighbor_page",
        "native_section_mapping_differs_from_extraction",
    ]
    assert diagnostic_status(issues) == "warning"
    assert diagnostic_status(
        ownership_issues(None, None)
    ) == "error"
    assert diagnostic_status([]) == "ok"
