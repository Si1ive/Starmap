"""Document asset normalization, matching, and local file persistence."""

import base64
import uuid
from pathlib import Path
from typing import List, Optional

from app.core.logging import get_logger
from app.modules.corpus.parser_types import ParsedAsset

logger = get_logger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parents[3]


def normalize_asset_type(asset_type: Optional[str]) -> str:
    """Normalize parser asset types to the database enum values."""
    value = (asset_type or "figure").strip().lower()
    if value in {"figure", "table", "formula", "page_crop", "other"}:
        return value
    if value in {"img", "image", "picture", "chart"}:
        return "figure"
    if value in {"eq", "formula_block", "formula_img", "equation"}:
        return "formula"
    return "other"


def normalize_asset_type_with_hint(
    asset_type: Optional[str],
    has_image_hint: bool = False,
) -> str:
    """Normalize code blocks as figures only when an image is present."""
    value = (asset_type or "figure").strip().lower()
    if value == "code":
        return "figure" if has_image_hint else "other"
    return normalize_asset_type(value)


def asset_type_key_candidates(
    asset_type: Optional[str],
    has_image_hint: bool = False,
) -> List[str]:
    """Return raw and normalized type keys used to bridge assets to blocks."""
    raw_type = (asset_type or "figure").strip().lower()
    normalized = normalize_asset_type_with_hint(
        raw_type,
        has_image_hint=has_image_hint,
    )
    if raw_type and raw_type != normalized:
        return [normalized, raw_type]
    return [normalized]


def is_image_path_hint(path_value: Optional[str]) -> bool:
    if not path_value:
        return False
    value = str(path_value).strip().lower()
    if not value:
        return False
    return any(
        value.endswith(suffix)
        for suffix in (
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".bmp",
            ".tiff",
        )
    )


def resolve_asset_file_path(
    asset_data: ParsedAsset,
    persisted_path: Optional[str],
) -> Optional[str]:
    """Resolve an asset path that is readable by the main backend."""
    if persisted_path:
        return persisted_path

    raw_path = getattr(asset_data, "file_path", None)
    if not raw_path:
        return None

    path = Path(raw_path)
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend(
            [
                BACKEND_ROOT / path,
                Path.cwd() / path,
                Path("/tmp") / path,
            ]
        )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    for base_dir in (BACKEND_ROOT, Path("/tmp")):
        for found in base_dir.rglob(path.name):
            if found.is_file():
                return str(found)

    return None


def write_asset_image(
    document_id: str,
    asset_data: ParsedAsset,
) -> Optional[str]:
    """Persist an inline base64 asset and return its backend path."""
    encoded_image = getattr(asset_data, "image_base64", None)
    if not encoded_image:
        return None

    extension = getattr(asset_data, "image_ext", None) or ".png"
    destination_dir = BACKEND_ROOT / "uploads" / "assets" / document_id
    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{uuid.uuid4().hex[:32]}{extension}"
        destination.write_bytes(base64.b64decode(encoded_image))
        return str(destination)
    except Exception as exc:
        logger.warning(
            "资产图片落盘失败",
            document_id=document_id,
            error=str(exc),
        )
        return None


def asset_bbox_x1(bbox: Optional[dict]) -> Optional[float]:
    """Return a stable x1 key for block-to-asset matching."""
    if not bbox:
        return None
    x1 = bbox.get("x1")
    try:
        return round(float(x1), 1) if x1 is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "asset_bbox_x1",
    "asset_type_key_candidates",
    "is_image_path_hint",
    "normalize_asset_type",
    "normalize_asset_type_with_hint",
    "resolve_asset_file_path",
    "write_asset_image",
]
