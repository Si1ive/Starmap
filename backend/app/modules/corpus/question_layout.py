"""BBox-based grouping and parsing rules for extracted questions."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.modules.corpus.question_group_content import (
    EMBEDDED_QUESTION_NUMERIC_RE,
    OPTION_CONTINUATION_GAP_RATIO,
    OPTION_CONTINUATION_LEFT_MARGIN,
    QUESTION_CUE_RE,
    QUESTION_EXAMPLE_RE,
    QUESTION_NUMERIC_RE,
    QUESTION_PAREN_RE,
    QUESTION_TITLE_RE,
    classify_group,
    extract_figures,
    extract_full_stem,
    extract_options,
    extract_question_no,
    extract_stem,
    group_text,
    should_append_to_last_option,
)
from app.modules.corpus.question_layout_geometry import (
    COLUMN_GAP_MIN,
    COLUMN_MIN_BLOCKS_PER_COL,
    PageStats,
    bbox_x0,
    bbox_x1,
    bbox_y0,
    bbox_y1,
    check_dense_layout,
    column_left_edge,
    column_of,
    compute_page_stats,
    detect_columns,
    median,
    order_page_blocks,
)
from app.modules.corpus.question_option_rules import (
    CHOICE_BLANK_RE,
    OPTION_BLOCK_RE,
    OPTION_MARKER_RE,
    OPTION_SEPARATOR_RE,
    find_inline_option_start,
    find_recoverable_inline_option,
    has_inline_options,
    parse_options_from_text,
)

logger = get_logger(__name__)

# ===== QuestionLayoutGrouper: 基于 bbox 坐标的题目分组器 =====

# 阈值常量
LEFT_EDGE_MARGIN = OPTION_CONTINUATION_LEFT_MARGIN
GAP_RATIO_NEW_QUESTION = 3.0
GAP_RATIO_PAREN_Q = 1.5
GAP_RATIO_CONTINUATION = OPTION_CONTINUATION_GAP_RATIO
@dataclass
class BlockTag:
    block: Any
    at_left_edge: bool
    has_q_number: bool
    has_option: bool
    has_paren_q: bool
    is_media: bool
    is_noise: bool
    gap_ratio: float


@dataclass
class QuestionGroup:
    blocks: List[Any]
    page_no: int


class QuestionLayoutGrouper:
    """基于 bbox 坐标的题目分组器"""

    def __init__(self, blocks: List[Any]):
        self.blocks = blocks
        self.page_stats: Dict[int, PageStats] = {}

    # ---- Phase 1: 页面统计 ----

    def _compute_page_stats(self, page_no: int, page_blocks: List[Any]) -> PageStats:
        """Compatibility delegate for page-level geometry statistics."""
        return compute_page_stats(page_no, page_blocks)

    def _detect_columns(
        self, text_blocks: List[Any]
    ) -> Tuple[Optional[float], Optional[Dict[int, float]]]:
        """Compatibility delegate for two-column detection."""
        return detect_columns(text_blocks)

    def _column_of(self, block: Any, stats: PageStats) -> int:
        """Compatibility delegate for block column lookup."""
        return column_of(block, stats)

    def _order_page_blocks(self, page_blocks: List[Any], stats: PageStats) -> List[Any]:
        """Compatibility delegate for page reading order."""
        return order_page_blocks(page_blocks, stats)

    def _check_dense_layout(self, page_blocks: List[Any]) -> bool:
        """Compatibility delegate for dense layout detection."""
        return check_dense_layout(page_blocks)

    # ---- Phase 2: 逐 block 打标 ----

    @staticmethod
    def _col_left_edge(stats: PageStats, x0: Optional[float]) -> float:
        """Compatibility delegate for column-specific left edges."""
        return column_left_edge(stats, x0)

    def _tag_block(self, block: Any, stats: PageStats, prev_block: Optional[Any]) -> BlockTag:
        bbox = getattr(block, "bbox", None) or {}
        text = getattr(block, "content_text", None) or getattr(block, "content_md", None) or ""
        block_type = getattr(block, "block_type", "") or ""

        x0 = self._bbox_x0(bbox)
        at_left_edge = False
        if x0 is not None:
            # 双栏时用所属栏的左边缘，右栏题号（x0≈右栏起点）才能被判为贴边
            col_edge = self._col_left_edge(stats, x0)
            at_left_edge = (x0 - col_edge) < LEFT_EDGE_MARGIN

        has_q_number = bool(QUESTION_NUMERIC_RE.match(text.strip()))
        has_option = bool(OPTION_BLOCK_RE.match(text.strip()))
        has_paren_q = bool(QUESTION_PAREN_RE.match(text.strip()))
        is_media = block_type.lower() in ("figure", "table", "formula", "image", "chart")
        is_noise = block_type.lower() in ("header", "footer", "page_number", "aside_text", "page_footnote")

        gap_ratio = 0.0
        if prev_block is not None:
            prev_bbox = getattr(prev_block, "bbox", None) or {}
            prev_y1 = self._bbox_y1(prev_bbox)
            cur_y0 = self._bbox_y0(bbox)
            if prev_y1 is not None and cur_y0 is not None and stats.median_gap > 0:
                gap = cur_y0 - prev_y1
                gap_ratio = gap / stats.median_gap

        return BlockTag(
            block=block,
            at_left_edge=at_left_edge,
            has_q_number=has_q_number,
            has_option=has_option,
            has_paren_q=has_paren_q,
            is_media=is_media,
            is_noise=is_noise,
            gap_ratio=gap_ratio,
        )

    # ---- Phase 3: 题目边界判定 ----

    def group_into_questions(self) -> List[QuestionGroup]:
        """主入口：将 blocks 分组为题目列表"""
        if not self.blocks:
            return []

        # 按页组合 blocks
        pages: Dict[int, List[Any]] = {}
        for b in self.blocks:
            page_no = getattr(b, "page_no", None) or 1
            pages.setdefault(page_no, []).append(b)

        # 为每页计算 PageStats
        for page_no, page_blocks in pages.items():
            self.page_stats[page_no] = self._compute_page_stats(page_no, page_blocks)
            if self.page_stats[page_no].is_dense:
                logger.warning("检测到疑似多栏/密排页面，当前版本仅记录告警", page_no=page_no)

        groups: List[QuestionGroup] = []
        current_group_blocks: List[Any] = []
        prev_block: Optional[Any] = None

        all_blocks_ordered: List[Any] = []
        for page_no in sorted(pages.keys()):
            all_blocks_ordered.extend(
                self._order_page_blocks(pages[page_no], self.page_stats.get(page_no))
            )

        for i, block in enumerate(all_blocks_ordered):
            page_no = getattr(block, "page_no", None) or 1
            stats = self.page_stats.get(page_no)
            if stats is None:
                stats = PageStats(page_no=page_no, left_edge=50.0, median_gap=10.0, is_dense=False)
                self.page_stats[page_no] = stats

            prev = all_blocks_ordered[i - 1] if i > 0 else None
            tag = self._tag_block(block, stats, prev)

            if tag.is_noise:
                continue

            is_new_question = self._is_new_question_start(tag, prev_block)

            if is_new_question:
                if current_group_blocks:
                    groups.append(QuestionGroup(
                        blocks=current_group_blocks,
                        page_no=getattr(current_group_blocks[0], "page_no", None) or 1,
                    ))
                current_group_blocks = [block]
            else:
                current_group_blocks.append(block)

            prev_block = block

        if current_group_blocks:
            groups.append(QuestionGroup(
                blocks=current_group_blocks,
                page_no=getattr(current_group_blocks[0], "page_no", None) or 1,
            ))

        # Phase 5: 跨页合并
        groups = self._merge_cross_page_groups(groups)

        return groups

    def _is_new_question_start(self, tag: BlockTag, prev_block: Optional[Any]) -> bool:
        """判断是否为新题目起点"""
        if prev_block is None:
            return True

        # 选项/噪声块绝不可能是新题起点
        if tag.has_option or tag.is_noise:
            return False

        # 媒体块（图/表）通常不是新题起点，但 MinerU 有时把"题号+题干+数据表"
        # 整块识别成 table（如第47题），此时题号就在 media 块里。若 media 块
        # 左边缘且带阿拉伯数字题号，视为新题起点，避免整道题被并入前一题；
        # 否则（纯图表、无题号）仍归属当前题。
        if tag.is_media:
            return bool(tag.at_left_edge and tag.has_q_number)

        # 检查当前 block 是否有有效的 bbox（x0 和 y0 都能取到）
        bbox = getattr(tag.block, "bbox", None) or {}
        has_bbox = (
            self._bbox_x0(bbox) is not None
            and self._bbox_y0(bbox) is not None
        )

        if has_bbox:
            # ---- 有 bbox：题号锚定 ----
            # 一道题的边界由"题号"锚定，而非 block 间距。408 简答题常有
            # "题干 + 图/表 + 追问 + (1)(2) 小问"结构，中间的表格/图/续体
            # 没有题号，必须归属当前题，不能因大间距被误判成新题——否则一道题
            # 会被表格从中间切断（如第46题）。

            # A. 左边缘 + 阿拉伯数字题号 → 新题（最高置信度，覆盖选择题与大题）
            if tag.at_left_edge and tag.has_q_number:
                return True

            # 括号号 (1)(2) 是题内小问，绝不是新题起点；有它就明确归属当前题。
            if tag.has_paren_q:
                return False

            # 其余无题号块（续体、表格后的追问、跨栏延续）一律归属当前题。
            # 去掉原"大间距 + 长文本 → 新题"的规则 C：表格/图会撑大间距，
            # 是题目被切断的元凶，间距不再作为新题依据。
            return False

        # ---- 无 bbox：只认强题号（与有 bbox 分支一致）。
        # 括号号 (1)(2) 是题内小问，不作为新题起点，避免把简答题的小问拆成独立题。
        if tag.has_q_number:
            return True

        return False

    # ---- Phase 4: 组内处理 ----

    @staticmethod
    def _has_inline_options(text: str) -> bool:
        """Compatibility delegate for inline option detection."""
        return has_inline_options(text)

    @staticmethod
    def _find_inline_option_start(text: str) -> int:
        """Compatibility delegate for locating inline option A."""
        return find_inline_option_start(text)

    def _extract_stem(self, group: QuestionGroup) -> str:
        """Compatibility delegate for question stem extraction."""
        return extract_stem(group.blocks)

    def _extract_options(self, group: QuestionGroup) -> List[Dict[str, str]]:
        """Compatibility delegate for question option extraction."""
        return extract_options(group.blocks, self.page_stats)

    @staticmethod
    def _group_text(group: QuestionGroup) -> str:
        """Compatibility delegate for question group text assembly."""
        return group_text(group.blocks)

    @staticmethod
    def _extract_full_stem(group: QuestionGroup) -> str:
        """Compatibility delegate for subjective stem extraction."""
        return extract_full_stem(group.blocks)

    @staticmethod
    def _find_recoverable_inline_option(group: QuestionGroup) -> Optional[Tuple[int, int]]:
        """Compatibility delegate for recovering inline option A."""
        return find_recoverable_inline_option(group.blocks)

    def _should_append_to_last_option(self, option_block: Any, continuation_block: Any) -> bool:
        """Compatibility delegate for option continuation detection."""
        return should_append_to_last_option(
            option_block,
            continuation_block,
            self.page_stats,
        )

    def _parse_options_from_text(self, text: str) -> List[Dict[str, str]]:
        """Compatibility delegate for option text parsing."""
        return parse_options_from_text(text)

    def _extract_figures(self, group: QuestionGroup) -> List[str]:
        """Compatibility delegate for media block extraction."""
        return extract_figures(group.blocks)

    def _extract_question_no(self, group: QuestionGroup) -> Optional[int]:
        """Compatibility delegate for question number extraction."""
        return extract_question_no(group.blocks)

    def classify_group(
        self, group: QuestionGroup, options: List[Dict[str, str]], question_no: Optional[int]
    ) -> Tuple[str, str]:
        """判断一个组是题目还是知识点候选。

        返回 (label, reason)，label ∈ {"question", "knowledge_candidate", "uncertain"}。
        组题已经把拆散的选项/跨页内容合并好，所以"有选项"是题目的强信号。
        判定顺序按置信度从高到低：
          1. 有 ≥2 个选项 → 题目（最强，选择题）
          2. 有题号(1./（1）/第一题) → 题目
          3. 有明确疑问特征(下列/正确的是/？等) → 题目（大题/简答）
          4. 都没有 → 知识点候选(uncertain，交给上层决定或 LLM)
        """
        return classify_group(group.blocks, options, question_no)

    # ---- Phase 5: 跨页处理 ----

    def _merge_cross_page_groups(self, groups: List[QuestionGroup]) -> List[QuestionGroup]:
        """合并跨页的题目"""
        if len(groups) < 2:
            return groups

        merged: List[QuestionGroup] = []
        i = 0
        while i < len(groups):
            current = groups[i]
            next_group = groups[i + 1] if i + 1 < len(groups) else None

            if next_group and self._should_merge_groups(current, next_group):
                combined = QuestionGroup(
                    blocks=current.blocks + next_group.blocks,
                    page_no=current.page_no,
                )
                merged.append(combined)
                i += 2
            else:
                merged.append(current)
                i += 1

        return merged

    def _should_merge_groups(self, current: QuestionGroup, next_group: QuestionGroup) -> bool:
        cur_has_options = any(
            OPTION_BLOCK_RE.match(
                (getattr(b, "content_text", None) or getattr(b, "content_md", None) or "").strip()
            )
            for b in current.blocks
        )
        if cur_has_options:
            return False

        # 当前组只有题干没有选项，且下组开头是选项
        next_blocks = next_group.blocks
        if not next_blocks:
            return False
        first_text = (
            getattr(next_blocks[0], "content_text", None) or
            getattr(next_blocks[0], "content_md", None) or ""
        ).strip()
        if OPTION_BLOCK_RE.match(first_text) and not QUESTION_NUMERIC_RE.match(first_text):
            return True

        return False

    # ---- 坐标辅助方法 ----

    @staticmethod
    def _bbox_x0(bbox: Optional[dict]) -> Optional[float]:
        """Compatibility delegate for bbox left edge."""
        return bbox_x0(bbox)

    @staticmethod
    def _bbox_y0(bbox: Optional[dict]) -> Optional[float]:
        """Compatibility delegate for bbox top edge."""
        return bbox_y0(bbox)

    @staticmethod
    def _bbox_x1(bbox: Optional[dict]) -> Optional[float]:
        """Compatibility delegate for bbox right edge."""
        return bbox_x1(bbox)

    @staticmethod
    def _bbox_y1(bbox: Optional[dict]) -> Optional[float]:
        """Compatibility delegate for bbox bottom edge."""
        return bbox_y1(bbox)

    @staticmethod
    def _median(values: List[float]) -> float:
        """Compatibility delegate for median calculation."""
        return median(values)

__all__ = [
    "BlockTag",
    "CHOICE_BLANK_RE",
    "COLUMN_GAP_MIN",
    "COLUMN_MIN_BLOCKS_PER_COL",
    "EMBEDDED_QUESTION_NUMERIC_RE",
    "GAP_RATIO_CONTINUATION",
    "GAP_RATIO_NEW_QUESTION",
    "GAP_RATIO_PAREN_Q",
    "LEFT_EDGE_MARGIN",
    "OPTION_BLOCK_RE",
    "OPTION_MARKER_RE",
    "OPTION_SEPARATOR_RE",
    "PageStats",
    "QUESTION_CUE_RE",
    "QUESTION_EXAMPLE_RE",
    "QUESTION_NUMERIC_RE",
    "QUESTION_PAREN_RE",
    "QUESTION_TITLE_RE",
    "QuestionGroup",
    "QuestionLayoutGrouper",
]
