"""题目组内容提取纯规则测试。"""

from types import SimpleNamespace

from app.modules.corpus.question_group_content import (
    classify_group,
    extract_figures,
    extract_options,
    extract_question_no,
    extract_stem,
)
from app.modules.corpus.question_layout_geometry import PageStats


def _block(
    *,
    text: str = "",
    block_type: str = "paragraph",
    block_id: str = "block-1",
    page_no: int = 1,
    bbox: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=block_id,
        page_no=page_no,
        block_type=block_type,
        bbox=bbox,
        content_text=text,
        content_md=None,
    )


def test_subjective_register_names_remain_in_stem() -> None:
    text = (
        "43 （12 分）整数 x 和 y 分别存放在寄存器 A 和 B 中，"
        "另外还有寄存器 C 和 D。请回答下列问题："
        "（1）A 和 B 中的内容是什么？"
        "（2）相加结果存放在 C 中，内容是什么？"
    )
    blocks = [_block(text=text)]

    assert extract_stem(blocks) == text
    assert extract_options(blocks, {}) == []


def test_inline_choice_stem_and_options_are_split() -> None:
    blocks = [
        _block(
            text=(
                "1。循环队列队首位置是（ ）。"
                "A rear-length B (rear-length+m) MOD m "
                "C (rear+1-length+m) MOD m D rear+length"
            )
        )
    ]

    assert extract_stem(blocks) == "1。循环队列队首位置是（ ）。"
    assert [option["label"] for option in extract_options(blocks, {})] == [
        "A",
        "B",
        "C",
        "D",
    ]


def test_option_continuation_uses_page_gap() -> None:
    blocks = [
        _block(text="27。题干（ ）。"),
        _block(
            text="A Ⅰ B Ⅱ C Ⅰ和Ⅱ D 都不",
            bbox={"x1": 86, "y1": 531, "x2": 466, "y2": 552},
        ),
        _block(
            text="处于死锁状态",
            bbox={"x1": 47, "y1": 556, "x2": 119, "y2": 576},
        ),
    ]
    page_stats = {
        1: PageStats(
            page_no=1,
            left_edge=47.0,
            median_gap=6.0,
            is_dense=False,
        )
    }

    options = extract_options(blocks, page_stats)

    assert options[-1]["text"] == "都不 处于死锁状态"


def test_extract_figures_returns_only_media_ids() -> None:
    blocks = [
        _block(text="题干", block_id="stem"),
        _block(block_type="figure", block_id="figure-1"),
        _block(block_type="table", block_id="table-1"),
        _block(text="续文", block_id="paragraph-1"),
    ]

    assert extract_figures(blocks) == ["figure-1", "table-1"]


def test_question_number_and_group_classification() -> None:
    numbered_blocks = [_block(text="27。题目内容")]
    cue_blocks = [_block(text="请说明该算法的时间复杂度。")]

    assert extract_question_no(numbered_blocks) == 27
    assert classify_group(numbered_blocks, [], 27) == (
        "question",
        "has_question_no",
    )
    assert classify_group(cue_blocks, [], None) == (
        "question",
        "has_cue",
    )
    assert classify_group([_block(text="操作系统基本概念")], [], None) == (
        "uncertain",
        "no_signal",
    )
