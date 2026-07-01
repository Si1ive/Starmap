"""
QuestionLayoutGrouper 测试

验证基于 bbox 坐标的题目分组器各 Phase 的正确性。
"""
import pytest
from types import SimpleNamespace

from app.services.entity_extraction_service import (
    QuestionLayoutGrouper,
    PageStats,
    BlockTag,
    QuestionGroup,
    LEFT_EDGE_MARGIN,
    GAP_RATIO_NEW_QUESTION,
    GAP_RATIO_PAREN_Q,
    GAP_RATIO_CONTINUATION,
)


def _block(
    page_no=1,
    block_type="paragraph",
    bbox=None,
    text="",
    block_id="b1",
    order_no=0,
):
    """快捷构造 DocumentBlock-like 对象"""
    return SimpleNamespace(
        id=block_id,
        page_no=page_no,
        block_type=block_type,
        bbox=bbox,
        content_text=text,
        content_md=None,
        order_no=order_no,
    )


# ---- Phase 1: 页面统计 ----

class TestPageStats:
    def test_left_edge_from_min_x0(self):
        blocks = [
            _block(bbox={"x1": 70, "y1": 100, "x2": 200, "y2": 120}),
            _block(bbox={"x1": 47, "y1": 200, "x2": 300, "y2": 220}),
            _block(bbox={"x1": 90, "y1": 300, "x2": 250, "y2": 320}),
        ]
        grouper = QuestionLayoutGrouper(blocks)
        stats = grouper._compute_page_stats(1, blocks)
        assert stats.left_edge == 47.0

    def test_median_gap(self):
        blocks = [
            _block(bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120}),
            _block(bbox={"x1": 50, "y1": 130, "x2": 200, "y2": 150}),  # gap=10
            _block(bbox={"x1": 50, "y1": 170, "x2": 200, "y2": 190}),  # gap=20
            _block(bbox={"x1": 50, "y1": 250, "x2": 200, "y2": 270}),  # gap=60
        ]
        grouper = QuestionLayoutGrouper(blocks)
        stats = grouper._compute_page_stats(1, blocks)
        # gaps: 10, 20, 60 → median = 20
        assert stats.median_gap == 20.0

    def test_median_gap_minimum_one(self):
        blocks = [
            _block(bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120}),
            _block(bbox={"x1": 50, "y1": 120, "x2": 200, "y2": 140}),  # gap=0
        ]
        grouper = QuestionLayoutGrouper(blocks)
        stats = grouper._compute_page_stats(1, blocks)
        assert stats.median_gap >= 1.0

    def test_is_dense_false_for_single_column(self):
        blocks = [
            _block(bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120}),
            _block(bbox={"x1": 50, "y1": 140, "x2": 200, "y2": 160}),
            _block(bbox={"x1": 50, "y1": 180, "x2": 200, "y2": 200}),
        ]
        grouper = QuestionLayoutGrouper(blocks)
        stats = grouper._compute_page_stats(1, blocks)
        assert stats.is_dense is False

    def test_is_dense_true_for_multi_column(self):
        # 同一 y 桶内有多个 block
        blocks = [
            _block(bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120}),
            _block(bbox={"x1": 300, "y1": 100, "x2": 450, "y2": 120}),
            _block(bbox={"x1": 550, "y1": 100, "x2": 700, "y2": 120}),
            _block(bbox={"x1": 50, "y1": 200, "x2": 200, "y2": 220}),
        ]
        grouper = QuestionLayoutGrouper(blocks)
        stats = grouper._compute_page_stats(1, blocks)
        assert stats.is_dense is True


# ---- Phase 2: 逐 block 打标 ----

class TestBlockTagging:
    def test_at_left_edge(self):
        stats = PageStats(page_no=1, left_edge=47.0, median_gap=10.0, is_dense=False)
        block = _block(bbox={"x1": 70, "y1": 100, "x2": 200, "y2": 120})
        grouper = QuestionLayoutGrouper([])
        tag = grouper._tag_block(block, stats, None)
        # 70 - 47 = 23 < 30 → at_left_edge
        assert tag.at_left_edge is True

    def test_not_at_left_edge(self):
        stats = PageStats(page_no=1, left_edge=47.0, median_gap=10.0, is_dense=False)
        block = _block(bbox={"x1": 200, "y1": 100, "x2": 400, "y2": 120})
        grouper = QuestionLayoutGrouper([])
        tag = grouper._tag_block(block, stats, None)
        assert tag.at_left_edge is False

    def test_has_q_number(self):
        stats = PageStats(page_no=1, left_edge=50.0, median_gap=10.0, is_dense=False)
        block = _block(bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120}, text="27。利用死锁定理")
        grouper = QuestionLayoutGrouper([])
        tag = grouper._tag_block(block, stats, None)
        assert tag.has_q_number is True

    def test_has_option(self):
        stats = PageStats(page_no=1, left_edge=50.0, median_gap=10.0, is_dense=False)
        block = _block(bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120}, text="A 。Ⅰ B 。Ⅱ")
        grouper = QuestionLayoutGrouper([])
        tag = grouper._tag_block(block, stats, None)
        assert tag.has_option is True

    def test_has_paren_q(self):
        stats = PageStats(page_no=1, left_edge=50.0, median_gap=10.0, is_dense=False)
        block = _block(bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120}, text="（1）下列选项中")
        grouper = QuestionLayoutGrouper([])
        tag = grouper._tag_block(block, stats, None)
        assert tag.has_paren_q is True

    def test_is_media(self):
        stats = PageStats(page_no=1, left_edge=50.0, median_gap=10.0, is_dense=False)
        block = _block(bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120}, block_type="figure")
        grouper = QuestionLayoutGrouper([])
        tag = grouper._tag_block(block, stats, None)
        assert tag.is_media is True

    def test_is_noise(self):
        stats = PageStats(page_no=1, left_edge=50.0, median_gap=10.0, is_dense=False)
        block = _block(bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120}, block_type="header")
        grouper = QuestionLayoutGrouper([])
        tag = grouper._tag_block(block, stats, None)
        assert tag.is_noise is True

    def test_gap_ratio(self):
        stats = PageStats(page_no=1, left_edge=50.0, median_gap=10.0, is_dense=False)
        prev = _block(bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120})
        cur = _block(bbox={"x1": 50, "y1": 150, "x2": 200, "y2": 170})
        grouper = QuestionLayoutGrouper([])
        tag = grouper._tag_block(cur, stats, prev)
        # gap = 150 - 120 = 30, ratio = 30/10 = 3.0
        assert tag.gap_ratio == 3.0

    def test_gap_ratio_first_block(self):
        stats = PageStats(page_no=1, left_edge=50.0, median_gap=10.0, is_dense=False)
        block = _block(bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120})
        grouper = QuestionLayoutGrouper([])
        tag = grouper._tag_block(block, stats, None)
        assert tag.gap_ratio == 0.0


# ---- Phase 3: 题目边界判定 ----

class TestQuestionBoundary:
    def test_first_block_is_question_start(self):
        tag = BlockTag(
            block=None, at_left_edge=True, has_q_number=False,
            has_option=False, has_paren_q=False, is_media=False,
            is_noise=False, gap_ratio=0.0,
        )
        grouper = QuestionLayoutGrouper([])
        assert grouper._is_new_question_start(tag, None) is True

    def test_left_edge_with_q_number(self):
        tag = BlockTag(
            block=_block(text="27。题目内容"),
            at_left_edge=True, has_q_number=True,
            has_option=False, has_paren_q=False, is_media=False,
            is_noise=False, gap_ratio=1.0,
        )
        grouper = QuestionLayoutGrouper([])
        assert grouper._is_new_question_start(tag, _block()) is True

    def test_left_edge_with_paren_q_and_gap(self):
        tag = BlockTag(
            block=_block(text="（1）子题内容", bbox={"x1": 50, "y1": 200, "x2": 200, "y2": 220}),
            at_left_edge=True, has_q_number=False,
            has_option=False, has_paren_q=True, is_media=False,
            is_noise=False, gap_ratio=2.0,
        )
        grouper = QuestionLayoutGrouper([])
        assert grouper._is_new_question_start(tag, _block()) is True

    def test_paren_q_low_gap_not_new_question(self):
        tag = BlockTag(
            block=_block(text="（2）子题", bbox={"x1": 50, "y1": 130, "x2": 200, "y2": 150}),
            at_left_edge=True, has_q_number=False,
            has_option=False, has_paren_q=True, is_media=False,
            is_noise=False, gap_ratio=1.0,
        )
        grouper = QuestionLayoutGrouper([])
        assert grouper._is_new_question_start(tag, _block()) is False

    def test_large_gap_with_text(self):
        tag = BlockTag(
            block=_block(text="这是一道没有题号的题目内容", bbox={"x1": 50, "y1": 400, "x2": 200, "y2": 420}),
            at_left_edge=False, has_q_number=False,
            has_option=False, has_paren_q=False, is_media=False,
            is_noise=False, gap_ratio=4.0,
        )
        grouper = QuestionLayoutGrouper([])
        assert grouper._is_new_question_start(tag, _block()) is True

    def test_option_block_not_new_question(self):
        tag = BlockTag(
            block=_block(text="A. 选项一"),
            at_left_edge=False, has_q_number=False,
            has_option=True, has_paren_q=False, is_media=False,
            is_noise=False, gap_ratio=1.0,
        )
        grouper = QuestionLayoutGrouper([])
        assert grouper._is_new_question_start(tag, _block()) is False

    def test_media_block_not_new_question(self):
        tag = BlockTag(
            block=_block(block_type="figure"),
            at_left_edge=False, has_q_number=False,
            has_option=False, has_paren_q=False, is_media=True,
            is_noise=False, gap_ratio=1.0,
        )
        grouper = QuestionLayoutGrouper([])
        assert grouper._is_new_question_start(tag, _block()) is False


# ---- Phase 3: 完整分组 ----

class TestGroupIntoQuestions:
    def test_single_question_with_media_and_options(self):
        """设计文档 3.1 的 case"""
        blocks = [
            _block(page_no=2, bbox={"x1": 70, "y1": 347, "x2": 418, "y2": 366},
                   text="27。利用死锁定理简化下列进程资源图，则处于死锁状态的是（ ）。", block_id="b1"),
            _block(page_no=2, bbox={"x1": 97, "y1": 374, "x2": 223, "y2": 505},
                   block_type="figure", block_id="b2"),
            _block(page_no=2, bbox={"x1": 269, "y1": 374, "x2": 415, "y2": 504},
                   block_type="figure", block_id="b3"),
            _block(page_no=2, bbox={"x1": 86, "y1": 531, "x2": 466, "y2": 552},
                   text="A 。Ⅰ B 。Ⅱ C。Ⅰ和Ⅱ D。都不", block_id="b4"),
            _block(page_no=2, bbox={"x1": 47, "y1": 556, "x2": 119, "y2": 576},
                   text="处于死锁状态", block_id="b5"),
        ]
        grouper = QuestionLayoutGrouper(blocks)
        groups = grouper.group_into_questions()
        assert len(groups) == 1
        assert len(groups[0].blocks) == 5

    def test_multiple_questions(self):
        blocks = [
            _block(page_no=1, bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120},
                   text="1。第一道题", block_id="q1"),
            _block(page_no=1, bbox={"x1": 50, "y1": 130, "x2": 200, "y2": 150},
                   text="A。选项A B。选项B C。选项C D。选项D", block_id="q1_opts"),
            _block(page_no=1, bbox={"x1": 50, "y1": 250, "x2": 200, "y2": 270},
                   text="2。第二道题", block_id="q2"),
            _block(page_no=1, bbox={"x1": 50, "y1": 280, "x2": 200, "y2": 300},
                   text="A。选项A B。选项B C。选项C D。选项D", block_id="q2_opts"),
        ]
        grouper = QuestionLayoutGrouper(blocks)
        groups = grouper.group_into_questions()
        assert len(groups) == 2
        assert len(groups[0].blocks) == 2
        assert len(groups[1].blocks) == 2

    def test_noise_blocks_skipped(self):
        blocks = [
            _block(page_no=1, bbox={"x1": 50, "y1": 10, "x2": 200, "y2": 20},
                   block_type="header", text="页眉", block_id="noise"),
            _block(page_no=1, bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120},
                   text="1。题目", block_id="q1"),
        ]
        grouper = QuestionLayoutGrouper(blocks)
        groups = grouper.group_into_questions()
        assert len(groups) == 1
        assert len(groups[0].blocks) == 1
        assert groups[0].blocks[0].id == "q1"

    def test_cross_page_merge(self):
        """跨页：第一页只有题干，第二页开头是选项"""
        blocks = [
            _block(page_no=1, bbox={"x1": 50, "y1": 800, "x2": 200, "y2": 820},
                   text="5。跨页题目题干（ ）。", block_id="q5_stem"),
            _block(page_no=2, bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120},
                   text="A。选项A B。选项B C。选项C D。选项D", block_id="q5_opts"),
        ]
        grouper = QuestionLayoutGrouper(blocks)
        groups = grouper.group_into_questions()
        assert len(groups) == 1
        assert len(groups[0].blocks) == 2


# ---- Phase 4: 组内处理 ----

class TestExtractStem:
    def test_stem_excludes_options_and_media(self):
        blocks = [
            _block(text="27。题干内容（ ）。", block_type="paragraph"),
            _block(block_type="figure"),
            _block(text="A 。Ⅰ B 。Ⅱ C。Ⅲ D。Ⅳ", block_type="paragraph"),
        ]
        group = QuestionGroup(blocks=blocks, page_no=1)
        grouper = QuestionLayoutGrouper([])
        stem = grouper._extract_stem(group)
        assert "27。题干内容（ ）。" in stem
        assert "A" not in stem

    def test_stem_concatenates_multiple_text_blocks(self):
        blocks = [
            _block(text="1。第一段题干", block_type="paragraph"),
            _block(text="第二段题干内容", block_type="paragraph"),
            _block(text="A。选项", block_type="paragraph"),
        ]
        group = QuestionGroup(blocks=blocks, page_no=1)
        grouper = QuestionLayoutGrouper([])
        stem = grouper._extract_stem(group)
        assert "第一段题干" in stem
        assert "第二段题干内容" in stem
        assert "A" not in stem


class TestExtractOptions:
    def test_extract_four_options(self):
        blocks = [
            _block(text="1。题干（ ）", block_type="paragraph"),
            _block(text="A 。选项一 B 。选项二 C。选项三 D。选项四", block_type="paragraph"),
        ]
        group = QuestionGroup(blocks=blocks, page_no=1)
        grouper = QuestionLayoutGrouper([])
        options = grouper._extract_options(group)
        assert len(options) == 4
        labels = [o["label"] for o in options]
        assert labels == ["A", "B", "C", "D"]

    def test_trailing_text_merged_to_last_option(self):
        """选项 D 尾部文字跨 block"""
        blocks = [
            _block(text="27。题干（ ）。", block_type="paragraph"),
            _block(
                text="A 。Ⅰ B 。Ⅱ C。Ⅰ和Ⅱ D。都不",
                block_type="paragraph",
                bbox={"x1": 86, "y1": 531, "x2": 466, "y2": 552},
            ),
            _block(
                text="处于死锁状态",
                block_type="paragraph",
                bbox={"x1": 47, "y1": 556, "x2": 119, "y2": 576},
            ),
        ]
        group = QuestionGroup(blocks=blocks, page_no=1)
        grouper = QuestionLayoutGrouper(blocks)
        grouper.page_stats[1] = PageStats(page_no=1, left_edge=47.0, median_gap=6.0, is_dense=False)
        options = grouper._extract_options(group)
        assert len(options) == 4
        assert "处于死锁状态" in options[3]["text"]

    def test_trailing_text_with_large_gap_is_not_merged(self):
        blocks = [
            _block(text="27。题干（ ）。", block_type="paragraph"),
            _block(
                text="A 。Ⅰ B 。Ⅱ C。Ⅰ和Ⅱ D。都不",
                block_type="paragraph",
                bbox={"x1": 86, "y1": 531, "x2": 466, "y2": 552},
            ),
            _block(
                text="28。下一题题干",
                block_type="paragraph",
                bbox={"x1": 47, "y1": 590, "x2": 260, "y2": 610},
            ),
        ]
        group = QuestionGroup(blocks=blocks, page_no=1)
        grouper = QuestionLayoutGrouper(blocks)
        grouper.page_stats[1] = PageStats(page_no=1, left_edge=47.0, median_gap=6.0, is_dense=False)
        options = grouper._extract_options(group)
        assert len(options) == 4
        assert "28。下一题题干" not in options[3]["text"]

    def test_no_options_returns_empty(self):
        blocks = [
            _block(text="简答题内容", block_type="paragraph"),
        ]
        group = QuestionGroup(blocks=blocks, page_no=1)
        grouper = QuestionLayoutGrouper([])
        options = grouper._extract_options(group)
        assert options == []


class TestExtractFigures:
    def test_extract_figure_ids(self):
        blocks = [
            _block(text="题干", block_type="paragraph", block_id="s1"),
            _block(block_type="figure", block_id="f1"),
            _block(block_type="table", block_id="t1"),
            _block(text="选项", block_type="paragraph", block_id="o1"),
        ]
        group = QuestionGroup(blocks=blocks, page_no=1)
        grouper = QuestionLayoutGrouper([])
        figures = grouper._extract_figures(group)
        assert set(figures) == {"f1", "t1"}


class TestExtractQuestionNo:
    def test_numeric_question_no(self):
        blocks = [_block(text="27。题目内容")]
        group = QuestionGroup(blocks=blocks, page_no=1)
        grouper = QuestionLayoutGrouper([])
        assert grouper._extract_question_no(group) == 27

    def test_paren_question_no(self):
        blocks = [_block(text="（5）子题内容")]
        group = QuestionGroup(blocks=blocks, page_no=1)
        grouper = QuestionLayoutGrouper([])
        assert grouper._extract_question_no(group) == 5

    def test_no_question_no(self):
        blocks = [_block(text="没有题号的内容")]
        group = QuestionGroup(blocks=blocks, page_no=1)
        grouper = QuestionLayoutGrouper([])
        assert grouper._extract_question_no(group) is None


# ---- Phase 5: 跨页合并 ----

class TestCrossPageMerge:
    def test_merge_stem_only_with_next_options(self):
        g1 = QuestionGroup(blocks=[
            _block(text="5。跨页题干（ ）。", block_id="stem"),
        ], page_no=1)
        g2 = QuestionGroup(blocks=[
            _block(text="A。选项A B。选项B C。选项C D。选项D", block_id="opts"),
        ], page_no=2)
        grouper = QuestionLayoutGrouper([])
        merged = grouper._merge_cross_page_groups([g1, g2])
        assert len(merged) == 1
        assert len(merged[0].blocks) == 2

    def test_no_merge_when_current_has_options(self):
        g1 = QuestionGroup(blocks=[
            _block(text="1。题干"),
            _block(text="A。选项A B。选项B C。选项C D。选项D"),
        ], page_no=1)
        g2 = QuestionGroup(blocks=[
            _block(text="2。下一题题干"),
        ], page_no=1)
        grouper = QuestionLayoutGrouper([])
        merged = grouper._merge_cross_page_groups([g1, g2])
        assert len(merged) == 2

    def test_no_merge_when_next_has_question_number(self):
        g1 = QuestionGroup(blocks=[
            _block(text="题干（ ）。", block_id="stem"),
        ], page_no=1)
        g2 = QuestionGroup(blocks=[
            _block(text="2。新题目", block_id="new_q"),
        ], page_no=2)
        grouper = QuestionLayoutGrouper([])
        merged = grouper._merge_cross_page_groups([g1, g2])
        assert len(merged) == 2


# ---- 边界情况 ----

class TestEdgeCases:
    def test_empty_blocks(self):
        grouper = QuestionLayoutGrouper([])
        groups = grouper.group_into_questions()
        assert groups == []

    def test_single_block(self):
        blocks = [_block(text="1。单独题目")]
        grouper = QuestionLayoutGrouper(blocks)
        groups = grouper.group_into_questions()
        assert len(groups) == 1
        assert len(groups[0].blocks) == 1

    def test_no_bbox_blocks(self):
        """无 bbox 的 block 也能正常处理（使用默认值）"""
        blocks = [
            _block(text="1。题目一", bbox=None),
            _block(text="A。选项A B。选项B", bbox=None),
            _block(text="2。题目二", bbox=None),
        ]
        grouper = QuestionLayoutGrouper(blocks)
        groups = grouper.group_into_questions()
        assert len(groups) == 2

    def test_mixed_pages(self):
        blocks = [
            _block(page_no=1, bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120},
                   text="1。第一页题目"),
            _block(page_no=2, bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120},
                   text="2。第二页题目"),
        ]
        grouper = QuestionLayoutGrouper(blocks)
        groups = grouper.group_into_questions()
        assert len(groups) == 2
        assert groups[0].page_no == 1
        assert groups[1].page_no == 2

    def test_large_gap_without_q_number_creates_new_question(self):
        """gap_ratio > 3.0 且有实质文本 → 新题目"""
        # 需要多个正常间距的 block 让 median_gap 保持较小，然后一个大间距触发
        blocks = [
            _block(page_no=1, bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120},
                   text="1。第一题"),
            _block(page_no=1, bbox={"x1": 50, "y1": 130, "x2": 200, "y2": 150},
                   text="A。选项 B。选项"),
            # 两个正常间距的 block 让 median_gap 稳定在 ~10
            _block(page_no=1, bbox={"x1": 50, "y1": 160, "x2": 200, "y2": 180},
                   text="2。第二题"),
            _block(page_no=1, bbox={"x1": 50, "y1": 190, "x2": 200, "y2": 210},
                   text="A。选项 B。选项"),
            # 大间距：gap=190, median_gap≈10, ratio≈19 > 3.0
            _block(page_no=1, bbox={"x1": 50, "y1": 400, "x2": 200, "y2": 420},
                   text="没有题号但内容足够长的题目文本"),
        ]
        grouper = QuestionLayoutGrouper(blocks)
        groups = grouper.group_into_questions()
        assert len(groups) == 3

    def test_small_gap_continuation(self):
        """小间距无题号 → 延续当前题"""
        blocks = [
            _block(page_no=1, bbox={"x1": 50, "y1": 100, "x2": 200, "y2": 120},
                   text="1。第一题"),
            _block(page_no=1, bbox={"x1": 50, "y1": 125, "x2": 200, "y2": 145},
                   text="题干的延续内容"),
        ]
        grouper = QuestionLayoutGrouper(blocks)
        groups = grouper.group_into_questions()
        assert len(groups) == 1
        assert len(groups[0].blocks) == 2
