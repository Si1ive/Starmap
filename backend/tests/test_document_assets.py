import base64
from pathlib import Path

from app.modules.corpus import document_assets
from app.modules.corpus.document_assets import (
    asset_bbox_x1,
    asset_type_key_candidates,
    is_image_path_hint,
    normalize_asset_type,
    normalize_asset_type_with_hint,
    resolve_asset_file_path,
    write_asset_image,
)
from app.modules.corpus.parser_types import ParsedAsset


def test_document_asset_types_normalize_parser_aliases_and_code_hints():
    assert normalize_asset_type("image") == "figure"
    assert normalize_asset_type("equation") == "formula"
    assert normalize_asset_type("code") == "other"
    assert normalize_asset_type_with_hint("code", has_image_hint=True) == "figure"
    assert asset_type_key_candidates("image") == ["figure", "image"]
    assert asset_type_key_candidates("code", has_image_hint=True) == [
        "figure",
        "code",
    ]


def test_document_asset_image_path_and_bbox_hints_are_stable():
    assert is_image_path_hint("assets/FIGURE.PNG")
    assert not is_image_path_hint("assets/figure.txt")
    assert asset_bbox_x1({"x1": "12.345"}) == 12.3
    assert asset_bbox_x1({"x1": "invalid"}) is None
    assert asset_bbox_x1(None) is None


def test_document_asset_path_resolution_uses_backend_relative_file(
    monkeypatch,
    tmp_path,
):
    asset_file = tmp_path / "mineru-output" / "figure.png"
    asset_file.parent.mkdir()
    asset_file.write_bytes(b"figure")
    monkeypatch.setattr(document_assets, "BACKEND_ROOT", tmp_path)

    resolved = resolve_asset_file_path(
        ParsedAsset(
            page_no=1,
            file_path="mineru-output/figure.png",
        ),
        persisted_path=None,
    )

    assert resolved == str(asset_file)


def test_document_asset_inline_image_is_persisted_under_backend_root(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(document_assets, "BACKEND_ROOT", tmp_path)
    payload = b"inline-figure"

    persisted = write_asset_image(
        "document-1",
        ParsedAsset(
            page_no=1,
            image_base64=base64.b64encode(payload).decode("ascii"),
            image_ext=".png",
        ),
    )

    assert persisted is not None
    assert persisted.startswith(str(tmp_path / "uploads" / "assets" / "document-1"))
    assert Path(persisted).read_bytes() == payload
