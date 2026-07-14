import pytest
from fastapi import HTTPException

from app.modules.corpus.mineru_parser import MinerUParser
from app.modules.corpus.parser_runtime import create_mineru_parser
from parser_service.main import _resolve_parser_name, root


def test_parser_service_compatibility_field_only_accepts_mineru():
    assert _resolve_parser_name(None) == "mineru"
    assert _resolve_parser_name(" MINERU ") == "mineru"

    with pytest.raises(HTTPException, match="固定使用 MinerU") as exc_info:
        _resolve_parser_name("docling")

    assert exc_info.value.status_code == 400


def test_embedded_runtime_always_creates_mineru():
    parser = create_mineru_parser({"deployment_target": "embedded"})

    assert isinstance(parser, MinerUParser)


@pytest.mark.asyncio
async def test_parser_service_root_exposes_single_engine_contract():
    payload = await root()

    assert payload["parser_name"] == "mineru"
    assert payload["default_parser"] == "mineru"
    assert payload["supported_parsers"] == ["mineru"]
