import base64

import pytest

from app.services.document_parsers import (
    MinerUParser,
    ParsedDocumentResult,
    _normalize_payload_block_type,
    _parsed_document_result_from_dict,
)


def _write_bytes(path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_mineru_parser_uses_table_body_and_img_path(monkeypatch, tmp_path):
    parser = MinerUParser()
    content_list = [
        {
            "type": "table",
            "page_idx": 4,
            "text": "",
            "bbox": [1, 2, 3, 4],
            "table_body": "<table><tr><td>a</td></tr></table>",
            "table_caption": ["表 1：示例"],
            "img_path": "images/table.png",
        },
    ]

    output_dir = tmp_path / "out"
    image_path = output_dir / "images" / "table.png"
    _write_bytes(image_path, b"image")

    monkeypatch.setattr(MinerUParser, "_find_content_list", lambda *_args: (content_list, None))

    result = parser._normalize_result(
        file_path="demo.pdf",
        result={"page_count": 6},
        output_dir=output_dir,
    )

    table_blocks = [b for b in result.blocks if b.block_type == "table"]
    table_assets = [a for a in result.assets if a.asset_type == "table"]

    assert len(table_blocks) == 1
    assert table_blocks[0].html_table == "<table><tr><td>a</td></tr></table>"
    assert len(table_assets) == 1
    assert table_assets[0].caption_text == "表 1：示例"
    assert table_assets[0].image_base64 == base64.b64encode(b"image").decode("ascii")


def test_mineru_parser_uses_img_path_for_image_block(monkeypatch, tmp_path):
    parser = MinerUParser()
    content_list = [
        {
            "type": "image",
            "page_idx": 0,
            "img_path": "images/figure.png",
            "image_caption": ["图 1"],
            "bbox": [10, 11, 12, 13],
            "text": "",
        }
    ]

    output_dir = tmp_path / "out2"
    image_path = output_dir / "images" / "figure.png"
    _write_bytes(image_path, b"fig")

    monkeypatch.setattr(MinerUParser, "_find_content_list", lambda *_args: (content_list, None))

    result = parser._normalize_result(
        file_path="demo.pdf",
        result={"page_count": 1},
        output_dir=output_dir,
    )

    assert len(result.assets) == 1
    asset = result.assets[0]
    assert asset.asset_type == "figure"
    assert asset.caption_text == "图 1"
    assert asset.image_base64 == base64.b64encode(b"fig").decode("ascii")


def test_parsed_document_result_from_dict_normalizes_image_payload_block_and_asset_types():
    payload = {
        "pages": [{"page_no": 1}],
        "blocks": [
            {
                "page_no": 1,
                "block_type": "paragraph",
                "type": "image",
                "order_no": 1,
                "content_text": "",
                "content_md": None,
                "bbox": {"x1": 1, "y1": 2, "x2": 3, "y2": 4},
            },
        ],
        "assets": [
            {
                "page_no": 1,
                "asset_type": "image",
                "file_path": "images/q27.png",
            }
        ],
    }

    parsed = _parsed_document_result_from_dict(
        parser_name="mineru",
        payload=payload,
        fallback_metadata={},
    )

    assert isinstance(parsed, ParsedDocumentResult)
    assert parsed.blocks[0].block_type == "figure"
    assert parsed.assets[0].asset_type == "figure"


def test_payload_block_type_preserves_noise_types_for_downstream_grouping():
    assert _normalize_payload_block_type("header") == "header"
    assert _normalize_payload_block_type("footer") == "footer"
    assert _normalize_payload_block_type("page_number") == "page_number"
    assert _normalize_payload_block_type("aside_text") == "aside_text"
    assert _normalize_payload_block_type("page_footnote") == "page_footnote"
