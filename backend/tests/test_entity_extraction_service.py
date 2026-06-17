from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.entity_extraction_service import EntityExtractionService, OptionIntegrityChecker


def test_choice_options_are_split_without_option_prefixes():
    service = EntityExtractionService(AsyncMock())

    stem, options = service._split_question_stem_options(
        "1. 关于CPU调度，下列说法正确的是？\n"
        "A. 先来先服务可能产生饥饿 B：时间片轮转适合分时系统\n"
        "C、短作业优先一定公平 D．优先级调度不能抢占"
    )

    assert stem == "1. 关于CPU调度，下列说法正确的是？"
    assert [opt["key"] for opt in options] == ["A", "B", "C", "D"]
    assert options[0]["text"] == "先来先服务可能产生饥饿"
    assert options[1]["text"] == "时间片轮转适合分时系统"


def test_choice_options_are_split_when_labels_have_no_punctuation():
    service = EntityExtractionService(AsyncMock())

    stem, options = service._split_question_stem_options(
        "10 从二叉树的任一结点出发到根的路径上 所经过的结点序列必按其关键字降序排列的是 （ ）。"
        "A 二叉排序树 B 大顶堆 C 小顶堆 D 平衡二叉树"
    )

    assert stem.startswith("10 从二叉树")
    assert [opt["key"] for opt in options] == ["A", "B", "C", "D"]
    assert options[0]["text"] == "二叉排序树"
    assert options[3]["text"] == "平衡二叉树"


def test_choice_options_are_split_with_mineru_punctuation_noise():
    service = EntityExtractionService(AsyncMock())

    stem, options = service._split_question_stem_options(
        "1 若循环队列以数组 Q[0 m−1]作为其存储结构 则循环队列的队首元素的实际位置是 （ ）。"
        "A <sub>． rear</sub>−length B 。 (rear−length+m) MOD mC 。 ( 1 +rear+m−length) MOD m "
        "D 。 (rear+length− 1 ) MOD m"
    )

    assert stem.startswith("1 若循环队列")
    assert [opt["key"] for opt in options] == ["A", "B", "C", "D"]
    assert options[0]["text"] == "rear−length"
    assert options[1]["text"] == "(rear−length+m) MOD m"
    assert options[2]["text"] == "( 1 +rear+m−length) MOD m"
    assert options[3]["text"] == "(rear+length− 1 ) MOD m"


def test_option_text_keeps_inner_abcd_words():
    service = EntityExtractionService(AsyncMock())

    _stem, options = service._split_question_stem_options(
        "9 一组数据建立的初始堆为 （ ）A 15 15 20 B 110 30 C 1510 15 D A B 和 C 均不正确"
    )

    assert options[3]["text"] == "A B 和 C 均不正确"


def test_option_text_can_start_with_another_option_label_letter():
    service = EntityExtractionService(AsyncMock())

    _stem, options = service._split_question_stem_options(
        "38 下图中 主机 A 发送一个 IP 数据报给主机 B 通信过程中以太网 1 上出现的以太网帧中承载一个 IP 数据报 "
        "该以太网帧中的 目 的地址和 IP 报头中的 目 的地址分别是 （ ） 。 "
        "A B 的 MAC 地址 B 的 IP 地址 B B 的 MAC 地址 R1 的 IP 地址"
        "C。 R1 的 MAC 地址， B 的 IP 地址 D。 R1 的 MAC 地址， R1 的 IP 地址"
    )

    assert [opt["key"] for opt in options] == ["A", "B", "C", "D"]
    assert options[0]["text"] == "B 的 MAC 地址 B 的 IP 地址"
    assert options[1]["text"] == "B 的 MAC 地址 R1 的 IP 地址"


def test_abcd_in_stem_does_not_force_choice_without_choice_signal():
    service = EntityExtractionService(AsyncMock())

    stem, options = service._split_question_stem_options(
        "43 假设寄存器 A 和 B 中存放两个整数，另外还有寄存器 C 和 D。请回答它们相加后的结果。"
    )

    assert options == []
    assert stem.startswith("43 假设寄存器 A 和 B")


def test_option_integrity_accepts_key_field():
    checker = OptionIntegrityChecker()

    result = checker.check({
        "question_type": "choice",
        "options": [
            {"key": "A", "text": "选项一"},
            {"key": "B", "text": "选项二"},
            {"key": "C", "text": "选项三"},
            {"key": "D", "text": "选项四"},
        ],
    })

    assert result["is_complete"] is True


def test_question_start_detection_does_not_treat_options_as_questions():
    service = EntityExtractionService(AsyncMock())

    option_block = SimpleNamespace(block_type="heading", content_text="A. 页表项包含物理块号", content_md=None)
    question_block = SimpleNamespace(block_type="paragraph", content_text="2. 下列关于页式存储管理的说法正确的是", content_md=None)

    assert service._is_question_start_block(option_block) is False
    assert service._is_question_start_block(question_block) is True


def test_question_start_detection_accepts_exam_number_formats():
    service = EntityExtractionService(AsyncMock())

    space_number_block = SimpleNamespace(
        block_type="paragraph",
        content_text="1 若循环队列以数组 Q[0 m-1]作为其存储结构，则队首元素位置是（ ）。A. rear",
        content_md=None,
    )
    chinese_period_block = SimpleNamespace(
        block_type="paragraph",
        content_text="2。 若一个栈以向量 V[1 n]存储，x 进栈的正确操作是（ ）。",
        content_md=None,
    )

    assert service._is_question_start_block(space_number_block) is True
    assert service._is_question_start_block(chinese_period_block) is True


def test_embedded_question_start_split_is_conservative():
    service = EntityExtractionService(AsyncMock())

    block = SimpleNamespace(
        id="block_1",
        document_id="doc_1",
        page_id=None,
        page_no=1,
        block_type="paragraph",
        order_no=1,
        content_text=(
            "12 已知一台计算机的 CPI 为 1.2，则运行时间为（ ）。A 40% B 60% C 80%"
            "13 已知小写英文字母 a 的 ASCII 码值为 61H，则校验码是（ ）。A 66H B E6H"
        ),
        content_md=None,
        content_json=None,
        bbox=None,
        latex=None,
        html_table=None,
        asset_id=None,
        confidence=None,
        review_status="pending",
    )

    parts = service._split_block_by_embedded_question_starts(block)

    assert len(parts) == 2
    assert parts[0].content_text.startswith("12 已知")
    assert parts[1].content_text.startswith("13 已知")


def test_embedded_question_start_split_ignores_unrelated_numbers():
    service = EntityExtractionService(AsyncMock())

    block = SimpleNamespace(
        id="block_1",
        document_id="doc_1",
        page_id=None,
        page_no=1,
        block_type="paragraph",
        order_no=1,
        content_text="31 若用 8 个字组成位示图管理内存，归还块号为 100 的位置为（ ）。A 字号为 3",
        content_md=None,
        content_json=None,
        bbox=None,
        latex=None,
        html_table=None,
        asset_id=None,
        confidence=None,
        review_status="pending",
    )

    parts = service._split_block_by_embedded_question_starts(block)

    assert len(parts) == 1
