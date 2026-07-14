import base64

import pytest

from app.modules.corpus.parser_runtime import (
    create_mineru_parser,
    inspect_mineru_health,
    validate_mineru_parser_name,
)
from app.modules.corpus.mineru_parser import MinerUParser
from app.modules.corpus.parser_service_client import (
    normalize_payload_block_type,
    parsed_document_result_from_dict,
)
from app.modules.corpus.parser_types import ParsedDocumentResult


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

    parsed = parsed_document_result_from_dict(
        parser_name="mineru",
        payload=payload,
        fallback_metadata={},
    )

    assert isinstance(parsed, ParsedDocumentResult)
    assert parsed.blocks[0].block_type == "figure"
    assert parsed.assets[0].asset_type == "figure"


def test_payload_block_type_preserves_noise_types_for_downstream_grouping():
    assert normalize_payload_block_type("header") == "header"
    assert normalize_payload_block_type("footer") == "footer"
    assert normalize_payload_block_type("page_number") == "page_number"
    assert normalize_payload_block_type("aside_text") == "aside_text"
    assert normalize_payload_block_type("page_footnote") == "page_footnote"


class _ServiceResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"json"
        self.text = "json"

    def json(self):
        return self._payload


def _remote_runtime_config():
    return {
        "active_parser": "mineru",
        "deployment_target": "remote",
        "remote_service_endpoint": "https://parser.example.test",
        "request_timeout_seconds": 120,
        "processing_window_size": 2,
    }


def test_parser_compatibility_field_only_accepts_mineru():
    validate_mineru_parser_name(None)
    validate_mineru_parser_name(" MINERU ")

    with pytest.raises(ValueError, match="固定使用 MinerU"):
        validate_mineru_parser_name("docling")


def test_remote_parser_service_posts_file_with_runtime_options(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF")
    captured = {}

    def fake_post(url, *, data, files, timeout):
        captured.update(url=url, data=data, files=files, timeout=timeout)
        return _ServiceResponse({
            "code": 200,
            "data": {
                "parser_name": "mineru",
                "parser_version": "3.3",
                "pages": [{"page_no": 1}],
                "blocks": [],
                "assets": [],
                "document_markdown": "# parsed",
            },
        })

    monkeypatch.setattr(
        "app.modules.corpus.parser_service_client.requests.post",
        fake_post,
    )

    parser = create_mineru_parser(_remote_runtime_config())
    result = parser.parse(str(pdf_path), task_id="run-1")

    assert captured["url"] == "https://parser.example.test/parse"
    assert captured["data"] == {
        "parser_name": "mineru",
        "processing_window_size": "2",
        "task_id": "run-1",
    }
    assert captured["timeout"] == 120
    assert result.document_markdown == "# parsed"
    assert result.metadata["deployment_target"] == "remote"


def test_remote_parser_service_fetches_progress(monkeypatch):
    captured = {}

    def fake_get(url, *, timeout):
        captured.update(url=url, timeout=timeout)
        return _ServiceResponse({
            "code": 200,
            "data": {
                "task_id": "run-2",
                "status": "parsing",
                "current_page": 3,
                "total_pages": 8,
            },
        })

    monkeypatch.setattr(
        "app.modules.corpus.parser_service_client.requests.get",
        fake_get,
    )

    parser = create_mineru_parser(_remote_runtime_config())
    progress = parser.fetch_progress("run-2")

    assert captured == {
        "url": "https://parser.example.test/progress/run-2",
        "timeout": 5,
    }
    assert progress["current_page"] == 3


def test_remote_parser_health_uses_configured_service(monkeypatch):
    captured = {}

    def fake_get(url, *, params, timeout):
        captured.update(url=url, params=params, timeout=timeout)
        return _ServiceResponse({
            "code": 200,
            "data": {
                "parser_name": "mineru",
                "parser_version": "3.3",
                "health_status": "ready",
                "is_available": True,
            },
        })

    monkeypatch.setattr("app.modules.corpus.parser_runtime.requests.get", fake_get)

    health = inspect_mineru_health(_remote_runtime_config())

    assert captured == {
        "url": "https://parser.example.test/health",
        "params": {"parser_name": "mineru"},
        "timeout": 10,
    }
    assert health["deployment_target"] == "remote"
    assert health["is_available"] is True
    assert health["health_status"] == "ready"
