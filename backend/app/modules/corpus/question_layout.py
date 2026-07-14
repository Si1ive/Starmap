"""BBox-based grouping and parsing rules for extracted questions."""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
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
from app.modules.corpus.question_type import is_subjective_question_text

logger = get_logger(__name__)


QUESTION_NUMERIC_RE = re.compile(r'^\s*(\d{1,3})(?:\s*[.、．。]\s*|\s+)(?=\S)')
EMBEDDED_QUESTION_NUMERIC_RE = re.compile(r'(?<!\d)(\d{1,3})(?:\s*[.、．。]\s*|\s+)(?=\S)')
QUESTION_TITLE_RE = re.compile(r'^\s*第\s*([一二三四五六七八九十百千\d]+)\s*题')
QUESTION_PAREN_RE = re.compile(r'^\s*[（(]\s*(\d{1,3})\s*[）)]\s*\S+')
QUESTION_EXAMPLE_RE = re.compile(r'^\s*例\s*\d+')
QUESTION_CUE_RE = re.compile(
    r'[?？]|下列|以下|关于|若|设|已知|正确|错误|不是|可以|能够|应|属于|采用|'
    r'给出|求|计算|证明|说明|分析|为什么|多少|哪个|哪些|如果|判断'
)


# ===== QuestionLayoutGrouper: 基于 bbox 坐标的题目分组器 =====

# 阈值常量
LEFT_EDGE_MARGIN = 30       # 0-1000 坐标系，约 3% 页宽
GAP_RATIO_NEW_QUESTION = 3.0
GAP_RATIO_PAREN_Q = 1.5
GAP_RATIO_CONTINUATION = 1.5
# 分栏检测（0-1000 坐标系）：双栏页的左右栏 x0 分布会出现两个聚集带，
# 中间有明显空隙。COLUMN_GAP_MIN 为两带间的最小空隙，低于此视为单栏。
COLUMN_GAP_MIN = 120        # 左右栏 x0 聚集带之间的最小间隔
COLUMN_MIN_BLOCKS_PER_COL = 3   # 每栏至少的文本块数，避免个别偏移块误判成栏


@dataclass
class PageStats:
    page_no: int
    left_edge: float
    median_gap: float
    is_dense: bool
    # 分栏：column_boundary 为 None 表示单栏；非 None 时为左右栏分界 x 坐标。
    # left_edge_by_col 记录每栏各自的左边缘（0=左栏,1=右栏），双栏时右栏题号
    # 需按右栏左边缘判断 at_left_edge，否则右栏题目永远无法被识别为新题起点。
    column_boundary: Optional[float] = None
    left_edge_by_col: Optional[Dict[int, float]] = None


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
        gaps: List[float] = []

        # 只对 text 类 block 计算左边缘和行距，排除 figure/table 等媒体块
        text_blocks = [
            b for b in page_blocks
            if (getattr(b, "block_type", "") or "").lower()
            not in (
                "figure", "table", "formula", "image", "chart",
                "header", "footer", "page_number", "aside_text", "page_footnote",
            )
        ]

        left_edges = [
            x0 for b in text_blocks
            if (x0 := self._bbox_x0(getattr(b, "bbox", None) or {})) is not None
        ]

        for i in range(1, len(text_blocks)):
            prev_bbox = getattr(text_blocks[i - 1], "bbox", None) or {}
            cur_bbox = getattr(text_blocks[i], "bbox", None) or {}
            prev_y1 = self._bbox_y1(prev_bbox)
            cur_y0 = self._bbox_y0(cur_bbox)
            if prev_y1 is not None and cur_y0 is not None:
                gap = cur_y0 - prev_y1
                if gap >= 0:
                    gaps.append(gap)

        page_left_edge = min(left_edges) if left_edges else 50.0
        median_gap = self._median(gaps) if gaps else 10.0
        is_dense = self._check_dense_layout(text_blocks)

        # 分栏检测：按 x0 分布找左右栏分界，双栏时每栏各算左边缘
        column_boundary, left_edge_by_col = self._detect_columns(text_blocks)

        return PageStats(
            page_no=page_no,
            left_edge=page_left_edge,
            median_gap=max(median_gap, 1.0),
            is_dense=is_dense,
            column_boundary=column_boundary,
            left_edge_by_col=left_edge_by_col,
        )

    def _detect_columns(
        self, text_blocks: List[Any]
    ) -> Tuple[Optional[float], Optional[Dict[int, float]]]:
        """检测页面是否双栏排版，返回 (分界x坐标, 每栏左边缘)。

        判据：block 的 x0 分布若明显聚成两簇（簇间存在宽间隙），即为双栏。
        单栏或样本不足返回 (None, None)。分界取两簇之间的中点。
        """
        x0s = sorted(
            x0 for b in text_blocks
            if (x0 := self._bbox_x0(getattr(b, "bbox", None) or {})) is not None
        )
        if len(x0s) < 6:
            return None, None

        # 找相邻 x0 的最大间隙，作为候选栏边界
        max_gap = 0.0
        gap_at = None
        for a, b in zip(x0s, x0s[1:]):
            if b - a > max_gap:
                max_gap = b - a
                gap_at = (a + b) / 2
        # 最大间隙需足够宽，且左右两侧都有足够 block，才认定为双栏
        if gap_at is None or max_gap < COLUMN_GAP_MIN:
            return None, None

        left = [x for x in x0s if x < gap_at]
        right = [x for x in x0s if x >= gap_at]
        if len(left) < COLUMN_MIN_BLOCKS_PER_COL or len(right) < COLUMN_MIN_BLOCKS_PER_COL:
            return None, None

        return gap_at, {0: min(left), 1: min(right)}

    def _column_of(self, block: Any, stats: PageStats) -> int:
        """返回 block 所在栏（0=左,1=右）；单栏恒为 0。"""
        if stats.column_boundary is None:
            return 0
        x0 = self._bbox_x0(getattr(block, "bbox", None) or {})
        if x0 is None:
            return 0
        return 1 if x0 >= stats.column_boundary else 0

    def _order_page_blocks(self, page_blocks: List[Any], stats: PageStats) -> List[Any]:
        """按阅读顺序重排一页内的 block。

        单栏：保持原 order_no（MinerU 输出顺序）。
        双栏：左栏整列（按 y 升序）→ 右栏整列（按 y 升序），修正 MinerU 跨栏交错。
        媒体/噪声块按其 y 坐标归入所在栏，保持与文本的相对位置。
        """
        if stats.column_boundary is None:
            return list(page_blocks)

        left_col: List[Any] = []
        right_col: List[Any] = []
        for b in page_blocks:
            col = self._column_of(b, stats)
            (left_col if col == 0 else right_col).append(b)

        def _y0(b: Any) -> float:
            v = self._bbox_y0(getattr(b, "bbox", None) or {})
            return v if v is not None else 0.0

        left_col.sort(key=_y0)
        right_col.sort(key=_y0)
        return left_col + right_col

    def _check_dense_layout(self, page_blocks: List[Any]) -> bool:
        """统计同 y 坐标的 block 数量，判断是否多栏排版"""
        y_buckets: Dict[int, int] = {}
        for b in page_blocks:
            bbox = getattr(b, "bbox", None) or {}
            y0 = self._bbox_y0(bbox)
            if y0 is None:
                continue
            bucket = int(y0 // 20)
            y_buckets[bucket] = y_buckets.get(bucket, 0) + 1
        total = sum(1 for v in y_buckets.values())
        if total == 0:
            return False
        multi = sum(1 for v in y_buckets.values() if v > 2)
        return (multi / total) > 0.3

    # ---- Phase 2: 逐 block 打标 ----

    @staticmethod
    def _col_left_edge(stats: PageStats, x0: Optional[float]) -> float:
        """取 block 所属栏的左边缘。单栏或无坐标时回退到全页左边缘。"""
        if x0 is None or stats.column_boundary is None or not stats.left_edge_by_col:
            return stats.left_edge
        col = 0 if x0 < stats.column_boundary else 1
        return stats.left_edge_by_col.get(col, stats.left_edge)

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
        if is_subjective_question_text(self._group_text(group)):
            return self._extract_full_stem(group)

        parts: List[str] = []
        in_options = False
        recoverable_inline = self._find_recoverable_inline_option(group)
        for block_idx, block in enumerate(group.blocks):
            text = getattr(block, "content_text", None) or getattr(block, "content_md", None) or ""
            text = text.strip()
            if not text:
                continue
            if OPTION_BLOCK_RE.match(text):
                in_options = True
            if in_options:
                continue
            block_type = getattr(block, "block_type", "") or ""
            if block_type.lower() in ("figure", "table", "formula", "image", "chart"):
                # media 块通常是纯图表，内容不混进题干。但 MinerU 常把"题干文字+数据表"
                # 混成一个 table 块（如第47题），块内带题号的文字正是题干，需纳入；
                # 纯图表（无题号文字）仍跳过。
                if QUESTION_NUMERIC_RE.match(text):
                    parts.append(text)
                continue
            if recoverable_inline and block_idx == recoverable_inline[0]:
                stem_part = text[:recoverable_inline[1]].strip()
                if stem_part:
                    parts.append(stem_part)
                in_options = True
                continue
            # 题干+选项同块：只保留选项标记之前的题干，选项部分留给 _extract_options 处理
            if self._has_inline_options(text):
                opt_start = self._find_inline_option_start(text)
                if opt_start > 0:
                    stem_part = text[:opt_start].strip()
                    if stem_part:
                        parts.append(stem_part)
                    in_options = True
                    continue
            parts.append(text)
        # 用空格而非换行拼接 stem
        return " ".join(parts)

    def _extract_options(self, group: QuestionGroup) -> List[Dict[str, str]]:
        """从组内提取选项（含跨 block 合并）"""
        if is_subjective_question_text(self._group_text(group)):
            return []

        option_blocks: List[Dict[str, Any]] = []
        non_option_after: List[Any] = []
        last_option_block: Optional[Any] = None

        option_phase = False
        recoverable_inline = self._find_recoverable_inline_option(group)
        for block_idx, block in enumerate(group.blocks):
            text = getattr(block, "content_text", None) or getattr(block, "content_md", None) or ""
            text = text.strip()
            block_type = getattr(block, "block_type", "") or ""

            if recoverable_inline and block_idx == recoverable_inline[0]:
                option_phase = True
                option_blocks.append({
                    "text": text[recoverable_inline[1]:],
                    "block": block,
                    "is_option": True,
                })
                last_option_block = block
            elif OPTION_BLOCK_RE.match(text):
                option_phase = True
                option_blocks.append({"text": text, "block": block, "is_option": True})
                last_option_block = block
            elif not option_phase and self._has_inline_options(text):
                # 题干+选项同块：切出选项标记之后的部分作为选项文本
                opt_start = self._find_inline_option_start(text)
                if opt_start >= 0:
                    option_phase = True
                    option_blocks.append({"text": text[opt_start:], "block": block, "is_option": True})
                    last_option_block = block
            elif option_phase:
                # 媒体块不应作为选项尾部文字合并
                if (
                    block_type.lower() not in ("figure", "table", "formula", "image", "chart")
                    and last_option_block is not None
                    and self._should_append_to_last_option(last_option_block, block)
                ):
                    non_option_after.append(block)

        if not option_blocks:
            return []

        # 从选项块中解析出各个选项
        all_option_text = " ".join(ob["text"] for ob in option_blocks)

        options = self._parse_options_from_text(all_option_text)

        # 处理跨 block 的选项尾部文字
        if non_option_after and options:
            trailing_text = " ".join(
                getattr(b, "content_text", None) or getattr(b, "content_md", None) or ""
                for b in non_option_after
            ).strip()
            if trailing_text and not QUESTION_NUMERIC_RE.match(trailing_text):
                options[-1]["text"] = options[-1]["text"] + " " + trailing_text

        return options

    @staticmethod
    def _group_text(group: QuestionGroup) -> str:
        return " ".join(
            (
                getattr(block, "content_text", None)
                or getattr(block, "content_md", None)
                or ""
            ).strip()
            for block in group.blocks
            if (
                getattr(block, "content_text", None)
                or getattr(block, "content_md", None)
                or ""
            ).strip()
        )

    @staticmethod
    def _extract_full_stem(group: QuestionGroup) -> str:
        parts: List[str] = []
        for block in group.blocks:
            text = (
                getattr(block, "content_text", None)
                or getattr(block, "content_md", None)
                or ""
            ).strip()
            if not text:
                continue
            block_type = (
                getattr(block, "block_type", "") or ""
            ).lower()
            if (
                block_type in (
                    "figure",
                    "table",
                    "formula",
                    "image",
                    "chart",
                )
                and not QUESTION_NUMERIC_RE.match(text)
            ):
                continue
            parts.append(text)
        return " ".join(parts)

    @staticmethod
    def _find_recoverable_inline_option(group: QuestionGroup) -> Optional[Tuple[int, int]]:
        """Compatibility delegate for recovering inline option A."""
        return find_recoverable_inline_option(group.blocks)

    def _should_append_to_last_option(self, option_block: Any, continuation_block: Any) -> bool:
        text = (
            getattr(continuation_block, "content_text", None)
            or getattr(continuation_block, "content_md", None)
            or ""
        ).strip()
        if not text:
            return False
        if QUESTION_NUMERIC_RE.match(text) or QUESTION_PAREN_RE.match(text) or OPTION_BLOCK_RE.match(text):
            return False

        option_bbox = getattr(option_block, "bbox", None) or {}
        cont_bbox = getattr(continuation_block, "bbox", None) or {}
        option_y1 = self._bbox_y1(option_bbox)
        cont_y0 = self._bbox_y0(cont_bbox)
        option_x0 = self._bbox_x0(option_bbox)
        option_x1 = self._bbox_x1(option_bbox)
        cont_x0 = self._bbox_x0(cont_bbox)

        if option_y1 is not None and cont_y0 is not None and cont_y0 < option_y1:
            return False

        page_no = getattr(option_block, "page_no", None) or getattr(continuation_block, "page_no", None) or 1
        stats = self.page_stats.get(page_no)
        if stats and option_y1 is not None and cont_y0 is not None:
            gap = max(0.0, cont_y0 - option_y1)
            gap_ratio = gap / max(stats.median_gap, 1.0)
            if gap_ratio >= GAP_RATIO_CONTINUATION:
                return False

        if option_x0 is not None and option_x1 is not None and cont_x0 is not None:
            if cont_x0 > option_x1 + LEFT_EDGE_MARGIN:
                return False

        return True

    def _parse_options_from_text(self, text: str) -> List[Dict[str, str]]:
        """Compatibility delegate for option text parsing."""
        return parse_options_from_text(text)

    def _extract_figures(self, group: QuestionGroup) -> List[str]:
        figure_ids: List[str] = []
        for block in group.blocks:
            block_type = getattr(block, "block_type", "") or ""
            if block_type.lower() in ("figure", "table", "formula", "image", "chart"):
                block_id = getattr(block, "id", None)
                if block_id:
                    figure_ids.append(block_id)
        return figure_ids

    def _extract_question_no(self, group: QuestionGroup) -> Optional[int]:
        for block in group.blocks:
            text = getattr(block, "content_text", None) or getattr(block, "content_md", None) or ""
            text = text.strip()
            m = QUESTION_NUMERIC_RE.match(text)
            if m:
                return int(m.group(1))
            m = QUESTION_PAREN_RE.match(text)
            if m:
                return int(m.group(1))
            m = QUESTION_TITLE_RE.match(text)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    pass
        return None

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
        if options and len(options) >= 2:
            return "question", "has_options"
        if question_no is not None:
            return "question", "has_question_no"

        # 疑问特征：合并组内全部文本再判，避免题干被拆到多个 block 时漏判
        joined = " ".join(
            (getattr(b, "content_text", None) or getattr(b, "content_md", None) or "")
            for b in group.blocks
        )
        if QUESTION_CUE_RE.search(joined):
            return "question", "has_cue"

        return "uncertain", "no_signal"

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
        """左边缘。MinerU 归一化存储 {x1: left, y1: top, x2: right, y2: bottom}"""
        if not bbox:
            return None
        val = bbox.get("x1")  # MinerU normalized: x1 = left
        if val is None:
            val = bbox.get("x0") or bbox.get("l")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bbox_y0(bbox: Optional[dict]) -> Optional[float]:
        """上边缘。MinerU 归一化存储 {x1: left, y1: top, x2: right, y2: bottom}"""
        if not bbox:
            return None
        val = bbox.get("y1")  # MinerU normalized: y1 = top
        if val is None:
            val = bbox.get("y0") or bbox.get("t")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bbox_x1(bbox: Optional[dict]) -> Optional[float]:
        """右边缘。MinerU 归一化存储 {x1: left, y1: top, x2: right, y2: bottom}"""
        if not bbox:
            return None
        val = bbox.get("x2")  # MinerU normalized: x2 = right
        if val is None:
            val = bbox.get("x1") or bbox.get("r")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bbox_y1(bbox: Optional[dict]) -> Optional[float]:
        """下边缘。MinerU 归一化存储 {x1: left, y1: top, x2: right, y2: bottom}"""
        if not bbox:
            return None
        val = bbox.get("y2")  # MinerU normalized: y2 = bottom
        if val is None:
            val = bbox.get("y1") or bbox.get("b")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _median(values: List[float]) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        if n % 2 == 1:
            return sorted_vals[n // 2]
        return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0

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
