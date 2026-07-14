"""题目布局的 bbox、分栏检测与页面统计规则。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


COLUMN_GAP_MIN = 120
COLUMN_MIN_BLOCKS_PER_COL = 3

_NON_TEXT_BLOCK_TYPES = {
    "figure",
    "table",
    "formula",
    "image",
    "chart",
    "header",
    "footer",
    "page_number",
    "aside_text",
    "page_footnote",
}


@dataclass
class PageStats:
    page_no: int
    left_edge: float
    median_gap: float
    is_dense: bool
    column_boundary: Optional[float] = None
    left_edge_by_col: Optional[Dict[int, float]] = None


def compute_page_stats(
    page_no: int,
    page_blocks: List[Any],
) -> PageStats:
    """计算单页文本块的左边缘、行距密度与分栏信息。"""
    text_blocks = [
        block
        for block in page_blocks
        if (getattr(block, "block_type", "") or "").lower()
        not in _NON_TEXT_BLOCK_TYPES
    ]
    left_edges = [
        x0
        for block in text_blocks
        if (
            x0 := bbox_x0(getattr(block, "bbox", None) or {})
        )
        is not None
    ]

    gaps: List[float] = []
    for index in range(1, len(text_blocks)):
        previous_bbox = getattr(
            text_blocks[index - 1],
            "bbox",
            None,
        ) or {}
        current_bbox = getattr(text_blocks[index], "bbox", None) or {}
        previous_y1 = bbox_y1(previous_bbox)
        current_y0 = bbox_y0(current_bbox)
        if previous_y1 is not None and current_y0 is not None:
            gap = current_y0 - previous_y1
            if gap >= 0:
                gaps.append(gap)

    page_left_edge = min(left_edges) if left_edges else 50.0
    median_gap = median(gaps) if gaps else 10.0
    column_boundary, left_edge_by_col = detect_columns(text_blocks)
    return PageStats(
        page_no=page_no,
        left_edge=page_left_edge,
        median_gap=max(median_gap, 1.0),
        is_dense=check_dense_layout(text_blocks),
        column_boundary=column_boundary,
        left_edge_by_col=left_edge_by_col,
    )


def detect_columns(
    text_blocks: List[Any],
) -> Tuple[Optional[float], Optional[Dict[int, float]]]:
    """按 x0 聚集带检测双栏页面。"""
    x0s = sorted(
        x0
        for block in text_blocks
        if (
            x0 := bbox_x0(getattr(block, "bbox", None) or {})
        )
        is not None
    )
    if len(x0s) < 6:
        return None, None

    max_gap = 0.0
    gap_at = None
    for left_x0, right_x0 in zip(x0s, x0s[1:]):
        if right_x0 - left_x0 > max_gap:
            max_gap = right_x0 - left_x0
            gap_at = (left_x0 + right_x0) / 2
    if gap_at is None or max_gap < COLUMN_GAP_MIN:
        return None, None

    left = [x0 for x0 in x0s if x0 < gap_at]
    right = [x0 for x0 in x0s if x0 >= gap_at]
    if (
        len(left) < COLUMN_MIN_BLOCKS_PER_COL
        or len(right) < COLUMN_MIN_BLOCKS_PER_COL
    ):
        return None, None
    return gap_at, {0: min(left), 1: min(right)}


def column_of(block: Any, stats: PageStats) -> int:
    """返回 block 所在栏，0 为左栏，1 为右栏。"""
    if stats.column_boundary is None:
        return 0
    x0 = bbox_x0(getattr(block, "bbox", None) or {})
    if x0 is None:
        return 0
    return 1 if x0 >= stats.column_boundary else 0


def order_page_blocks(
    page_blocks: List[Any],
    stats: PageStats,
) -> List[Any]:
    """按左栏从上到下、再右栏从上到下返回阅读顺序。"""
    if stats.column_boundary is None:
        return list(page_blocks)

    left_column: List[Any] = []
    right_column: List[Any] = []
    for block in page_blocks:
        target = left_column if column_of(block, stats) == 0 else right_column
        target.append(block)

    def sort_y0(block: Any) -> float:
        value = bbox_y0(getattr(block, "bbox", None) or {})
        return value if value is not None else 0.0

    left_column.sort(key=sort_y0)
    right_column.sort(key=sort_y0)
    return left_column + right_column


def check_dense_layout(page_blocks: List[Any]) -> bool:
    """统计同一纵坐标带的 block 数量，判断是否为密排页面。"""
    y_buckets: Dict[int, int] = {}
    for block in page_blocks:
        y0 = bbox_y0(getattr(block, "bbox", None) or {})
        if y0 is None:
            continue
        bucket = int(y0 // 20)
        y_buckets[bucket] = y_buckets.get(bucket, 0) + 1
    total = len(y_buckets)
    if total == 0:
        return False
    multi = sum(1 for count in y_buckets.values() if count > 2)
    return (multi / total) > 0.3


def column_left_edge(stats: PageStats, x0: Optional[float]) -> float:
    """返回 block 所属栏的左边缘。"""
    if (
        x0 is None
        or stats.column_boundary is None
        or not stats.left_edge_by_col
    ):
        return stats.left_edge
    column = 0 if x0 < stats.column_boundary else 1
    return stats.left_edge_by_col.get(column, stats.left_edge)


def bbox_x0(bbox: Optional[dict]) -> Optional[float]:
    """读取 MinerU bbox 左边缘。"""
    if not bbox:
        return None
    value = bbox.get("x1")
    if value is None:
        value = bbox.get("x0") or bbox.get("l")
    return _optional_float(value)


def bbox_y0(bbox: Optional[dict]) -> Optional[float]:
    """读取 MinerU bbox 上边缘。"""
    if not bbox:
        return None
    value = bbox.get("y1")
    if value is None:
        value = bbox.get("y0") or bbox.get("t")
    return _optional_float(value)


def bbox_x1(bbox: Optional[dict]) -> Optional[float]:
    """读取 MinerU bbox 右边缘。"""
    if not bbox:
        return None
    value = bbox.get("x2")
    if value is None:
        value = bbox.get("x1") or bbox.get("r")
    return _optional_float(value)


def bbox_y1(bbox: Optional[dict]) -> Optional[float]:
    """读取 MinerU bbox 下边缘。"""
    if not bbox:
        return None
    value = bbox.get("y2")
    if value is None:
        value = bbox.get("y1") or bbox.get("b")
    return _optional_float(value)


def median(values: List[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    count = len(sorted_values)
    if count % 2 == 1:
        return sorted_values[count // 2]
    return (
        sorted_values[count // 2 - 1]
        + sorted_values[count // 2]
    ) / 2.0


def _optional_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "COLUMN_GAP_MIN",
    "COLUMN_MIN_BLOCKS_PER_COL",
    "PageStats",
    "bbox_x0",
    "bbox_x1",
    "bbox_y0",
    "bbox_y1",
    "check_dense_layout",
    "column_left_edge",
    "column_of",
    "compute_page_stats",
    "detect_columns",
    "median",
    "order_page_blocks",
]
