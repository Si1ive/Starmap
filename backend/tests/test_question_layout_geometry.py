from types import SimpleNamespace

from app.modules.corpus.question_layout_geometry import (
    PageStats,
    bbox_x0,
    bbox_x1,
    bbox_y0,
    bbox_y1,
    check_dense_layout,
    column_left_edge,
    compute_page_stats,
    detect_columns,
    median,
    order_page_blocks,
)


def _block(
    block_id: str,
    *,
    x0: float,
    y0: float,
    x1: float = 200,
    y1: float = 120,
    block_type: str = "paragraph",
):
    return SimpleNamespace(
        id=block_id,
        block_type=block_type,
        bbox={"x1": x0, "y1": y0, "x2": x1, "y2": y1},
    )


def test_bbox_helpers_support_mineru_and_legacy_keys():
    assert bbox_x0({"x1": "10"}) == 10.0
    assert bbox_y0({"y1": "20"}) == 20.0
    assert bbox_x1({"x2": "30"}) == 30.0
    assert bbox_y1({"y2": "40"}) == 40.0
    assert bbox_x0({"l": 5}) == 5.0
    assert bbox_y1({"b": 45}) == 45.0
    assert bbox_x0({"x1": "invalid"}) is None


def test_compute_page_stats_ignores_media_and_calculates_gap():
    blocks = [
        _block("first", x0=60, y0=100, y1=120),
        _block(
            "figure",
            x0=10,
            y0=121,
            y1=125,
            block_type="figure",
        ),
        _block("second", x0=50, y0=140, y1=160),
        _block("third", x0=70, y0=200, y1=220),
    ]

    stats = compute_page_stats(3, blocks)

    assert stats.page_no == 3
    assert stats.left_edge == 50.0
    assert stats.median_gap == 30.0


def test_detect_columns_requires_two_populated_x0_clusters():
    blocks = [
        _block("l1", x0=50, y0=100),
        _block("l2", x0=55, y0=140),
        _block("l3", x0=60, y0=180),
        _block("r1", x0=550, y0=100),
        _block("r2", x0=555, y0=140),
        _block("r3", x0=560, y0=180),
    ]

    boundary, edges = detect_columns(blocks)

    assert boundary is not None
    assert edges == {0: 50.0, 1: 550.0}


def test_order_page_blocks_reads_left_column_before_right_column():
    blocks = [
        _block("right-late", x0=550, y0=200),
        _block("left-late", x0=50, y0=200),
        _block("right-early", x0=550, y0=100),
        _block("left-early", x0=50, y0=100),
    ]
    stats = PageStats(
        page_no=1,
        left_edge=50,
        median_gap=10,
        is_dense=False,
        column_boundary=300,
        left_edge_by_col={0: 50, 1: 550},
    )

    ordered = order_page_blocks(blocks, stats)

    assert [block.id for block in ordered] == [
        "left-early",
        "left-late",
        "right-early",
        "right-late",
    ]


def test_dense_layout_and_column_left_edge_rules():
    dense_blocks = [
        _block("a", x0=50, y0=100),
        _block("b", x0=250, y0=100),
        _block("c", x0=450, y0=100),
        _block("d", x0=50, y0=200),
    ]
    stats = PageStats(
        page_no=1,
        left_edge=50,
        median_gap=10,
        is_dense=True,
        column_boundary=300,
        left_edge_by_col={0: 50, 1: 550},
    )

    assert check_dense_layout(dense_blocks) is True
    assert column_left_edge(stats, 560) == 550
    assert column_left_edge(stats, None) == 50
    assert median([60, 10, 20]) == 20
    assert median([10, 20]) == 15
