from types import SimpleNamespace

from app.modules.corpus.question_option_rules import (
    find_inline_option_start,
    find_recoverable_inline_option,
    has_inline_options,
    parse_options_from_text,
)


def _block(text: str):
    return SimpleNamespace(content_text=text, content_md=None)


def test_has_inline_options_requires_option_a_and_multiple_labels():
    assert has_inline_options("题干 A 甲 B 乙 C 丙 D 丁") is True
    assert has_inline_options("题干 B 乙 C 丙 D 丁") is False
    assert has_inline_options("题干中只有 A 符号") is False


def test_find_inline_option_start_returns_marker_position():
    text = "30。题干内容（）。A 选项甲 B 选项乙"

    assert find_inline_option_start(text) == text.index("A")
    assert find_inline_option_start("没有选项") == -1


def test_find_recoverable_inline_option_locates_a_before_bcd_blocks():
    blocks = [
        _block("30。题干内容（）。A 选项甲"),
        _block("B 选项乙"),
        _block("C 选项丙"),
        _block("D 选项丁"),
    ]

    assert find_recoverable_inline_option(blocks) == (
        0,
        blocks[0].content_text.index("A"),
    )


def test_find_recoverable_inline_option_requires_b_as_first_option_block():
    blocks = [
        _block("30。题干内容（）。A 选项甲"),
        _block("C 选项丙"),
        _block("D 选项丁"),
    ]

    assert find_recoverable_inline_option(blocks) is None


def test_parse_options_from_text_supports_mineru_separators():
    options = parse_options_from_text(
        "A 。选项一 B．选项二 C、选项三 D: 选项四"
    )

    assert [option["key"] for option in options] == ["A", "B", "C", "D"]
    assert [option["text"] for option in options] == [
        "选项一",
        "选项二",
        "选项三",
        "选项四",
    ]


def test_parse_options_from_text_stops_at_repeated_marker():
    options = parse_options_from_text(
        "A 选项一 B 选项二 C 选项三 D 选项四 C 重复残块"
    )

    assert [option["key"] for option in options] == ["A", "B", "C", "D"]
    assert options[-1]["text"] == "选项四"


def test_parse_options_from_text_rejects_single_option():
    assert parse_options_from_text("A 唯一选项") == []
