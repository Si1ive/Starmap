import pytest
from pydantic import ValidationError

from app.modules.corpus.schemas import ParseCorpusFileRequest
from app.modules.operations.settings_service import SystemSettingsService


def test_legacy_parser_setting_is_normalized_to_mineru():
    merged = SystemSettingsService._merge_defaults(
        {
            "pdf_parser": {
                "active_parser": "docling",
                "service_mode": "single_active",
            }
        }
    )

    assert merged["pdf_parser"]["active_parser"] == "mineru"
    assert merged["pdf_parser"]["service_mode"] == "mineru_only"


def test_pdf_parser_input_is_sanitized_to_mineru():
    sanitized = SystemSettingsService._sanitize_input(
        {
            "pdf_parser": {
                "active_parser": "docling",
                "service_mode": "single_active",
            }
        }
    )

    assert sanitized["pdf_parser"]["active_parser"] == "mineru"
    assert sanitized["pdf_parser"]["service_mode"] == "mineru_only"


@pytest.mark.asyncio
async def test_pdf_parser_update_rejects_docling():
    service = SystemSettingsService(None)

    with pytest.raises(ValueError, match="固定为 mineru"):
        await service.update_pdf_parser("docling")


def test_parse_request_only_accepts_mineru():
    assert ParseCorpusFileRequest(parser_name="mineru").parser_name == "mineru"

    with pytest.raises(ValidationError):
        ParseCorpusFileRequest(parser_name="docling")
