"""Compatibility exports for document parsing."""

from pathlib import Path

from app.modules.corpus.document_parse_service import (
    BACKEND_ROOT,
    DocumentParseService,
    MinerUProgressHandler,
    _asset_type_key_candidates,
    _is_image_path_hint,
    _normalize_asset_type_for_db,
    _normalize_asset_type_for_db_with_hint,
    _resolve_asset_file_path,
    generate_id,
)
from app.services.document_parsers import (
    ParsedAsset,
    ParsedBlock,
    ParsedDocumentResult,
    ParsedPage,
    ParserUnavailableError,
)

__all__ = [
    "BACKEND_ROOT",
    "DocumentParseService",
    "MinerUProgressHandler",
    "ParsedAsset",
    "ParsedBlock",
    "ParsedDocumentResult",
    "ParsedPage",
    "ParserUnavailableError",
    "Path",
    "_asset_type_key_candidates",
    "_is_image_path_hint",
    "_normalize_asset_type_for_db",
    "_normalize_asset_type_for_db_with_hint",
    "_resolve_asset_file_path",
    "generate_id",
]
