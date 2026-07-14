"""Persistence and query operations for normalized parser output."""

import base64
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    CorpusFile,
    Document,
    DocumentAsset,
    DocumentBlock,
    DocumentPage,
)
from app.modules.corpus.text_cleaning import clean_block_text
from app.modules.corpus.parser_types import (
    ParsedAsset,
    ParsedBlock,
    ParsedDocumentResult,
    ParsedPage,
)

logger = get_logger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parents[3]


def generate_id() -> str:
    return uuid.uuid4().hex[:32]


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


class ParsedDocumentStore:
    """Persist normalized parser output and query the resulting document."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_document_by_corpus_file_id(
        self,
        corpus_file_id: str,
    ) -> Optional[Document]:
        result = await self.db.execute(
            select(Document).where(
                Document.corpus_file_id == corpus_file_id
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create_document(
        self,
        corpus_file: CorpusFile,
        parse_run_id: str,
    ) -> Document:
        """Get an existing document or create one for the corpus file."""
        document = await self.get_document_by_corpus_file_id(corpus_file.id)
        if not document:
            document = Document(
                id=generate_id(),
                corpus_file_id=corpus_file.id,
                title=corpus_file.file_name,
                doc_type=corpus_file.doc_type,
                language=corpus_file.language,
                status="pending",
            )
            self.db.add(document)

        document.latest_parse_run_id = parse_run_id
        await self.db.flush()
        return document

    @staticmethod
    def serialize_parse_result(
        parse_result: ParsedDocumentResult,
    ) -> Dict[str, Any]:
        return {
            "parser_name": parse_result.parser_name,
            "parser_version": parse_result.parser_version,
            "confidence": parse_result.confidence,
            "metadata": parse_result.metadata or {},
            "page_count": parse_result.page_count,
            "block_count": parse_result.block_count,
            "asset_count": parse_result.asset_count,
            "pages": [
                {
                    "page_no": page.page_no,
                    "width": page.width,
                    "height": page.height,
                }
                for page in parse_result.pages
            ],
            "blocks": [
                {
                    "page_no": block.page_no,
                    "block_type": block.block_type,
                    "order_no": block.order_no,
                    "content_text": block.content_text,
                    "content_md": block.content_md,
                    "bbox": block.bbox,
                    "html_table": block.html_table,
                    "latex": block.latex,
                }
                for block in parse_result.blocks
            ],
            "assets": [
                {
                    "page_no": asset.page_no,
                    "asset_type": asset.asset_type,
                    "caption_text": asset.caption_text,
                    "bbox": asset.bbox,
                    "file_path": asset.file_path,
                }
                for asset in parse_result.assets
            ],
        }

    async def persist_pages(
        self,
        document_id: str,
        pages: List[ParsedPage],
    ) -> None:
        """Replace page records for a reparsed document."""
        await self.db.execute(
            delete(DocumentPage).where(
                DocumentPage.document_id == document_id
            )
        )
        await self.db.flush()

        for page_data in pages:
            self.db.add(
                DocumentPage(
                    id=generate_id(),
                    document_id=document_id,
                    page_no=page_data.page_no,
                    width=page_data.width,
                    height=page_data.height,
                )
            )

        await self.db.flush()

    @staticmethod
    def write_asset_image(
        document_id: str,
        asset_data: ParsedAsset,
    ) -> Optional[str]:
        """Persist an inline base64 asset and return its backend path."""
        encoded_image = getattr(asset_data, "image_base64", None)
        if not encoded_image:
            return None

        extension = getattr(asset_data, "image_ext", None) or ".png"
        destination_dir = (
            BACKEND_ROOT / "uploads" / "assets" / document_id
        )
        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / f"{generate_id()}{extension}"
            destination.write_bytes(base64.b64decode(encoded_image))
            return str(destination)
        except Exception as exc:
            logger.warning(
                "资产图片落盘失败",
                document_id=document_id,
                error=str(exc),
            )
            return None

    @staticmethod
    def bbox_x1(bbox: Optional[dict]) -> Optional[float]:
        """Return a stable x1 key for block-to-asset matching."""
        if not bbox:
            return None
        x1 = bbox.get("x1")
        try:
            return round(float(x1), 1) if x1 is not None else None
        except (TypeError, ValueError):
            return None

    async def persist_assets(
        self,
        document_id: str,
        assets: List[ParsedAsset],
    ) -> None:
        """Replace assets and rebuild exact block-to-asset links."""
        await self.db.execute(
            delete(DocumentAsset).where(
                DocumentAsset.document_id == document_id
            )
        )
        await self.db.flush()

        media_blocks = (
            await self.db.execute(
                select(DocumentBlock).where(
                    DocumentBlock.document_id == document_id,
                    DocumentBlock.block_type.in_(
                        ["figure", "table", "formula", "code"]
                    ),
                )
            )
        ).scalars().all()
        for block in media_blocks:
            block.asset_id = None

        block_by_key: Dict[Any, Any] = {}
        fallback_blocks: Dict[Tuple[int, str], List[Any]] = {}
        for block in media_blocks:
            bbox_x1 = self.bbox_x1(block.bbox)
            block_by_key.setdefault(
                (block.page_no, block.block_type, bbox_x1),
                block,
            )
            if block.block_type == "code":
                block_by_key.setdefault(
                    (block.page_no, "figure", bbox_x1),
                    block,
                )
            if bbox_x1 is None:
                fallback_blocks.setdefault(
                    (block.page_no, block.block_type),
                    [],
                ).append(block)
                if block.block_type == "code":
                    fallback_blocks.setdefault(
                        (block.page_no, "figure"),
                        [],
                    ).append(block)

        explicit_keys = set()
        fallback_matched: Dict[Tuple[int, str], int] = {}
        for asset_data in assets:
            persisted_path = self.write_asset_image(
                document_id,
                asset_data,
            )
            has_image_hint = bool(
                asset_data.image_base64
            ) or is_image_path_hint(asset_data.file_path)
            asset_type = normalize_asset_type_with_hint(
                asset_data.asset_type,
                has_image_hint,
            )
            asset = DocumentAsset(
                id=generate_id(),
                document_id=document_id,
                page_no=asset_data.page_no,
                asset_type=asset_type,
                file_path=resolve_asset_file_path(
                    asset_data,
                    persisted_path,
                ),
                caption_text=asset_data.caption_text,
                bbox=asset_data.bbox,
                metadata_json=getattr(asset_data, "metadata", None),
            )
            self.db.add(asset)

            has_image_hint = is_image_path_hint(
                asset_data.file_path
            ) or bool(asset_data.image_base64)
            asset_x1 = self.bbox_x1(asset_data.bbox)
            matched = None
            for key in asset_type_key_candidates(
                asset_data.asset_type,
                has_image_hint=has_image_hint,
            ):
                keyed = (asset_data.page_no, key, asset_x1)
                explicit_keys.add(keyed)
                matched = block_by_key.get(keyed)
                if matched is not None:
                    matched.asset_id = asset.id
                    break

            if matched is None and asset_x1 is None:
                candidates_key = (
                    asset_data.page_no,
                    normalize_asset_type_with_hint(
                        asset_data.asset_type,
                        has_image_hint,
                    ),
                )
                candidates = fallback_blocks.get(candidates_key, [])
                if not candidates:
                    candidates = fallback_blocks.get(
                        (asset_data.page_no, "figure"),
                        [],
                    )
                candidate_position = fallback_matched.get(
                    candidates_key,
                    0,
                )
                if candidate_position < len(candidates):
                    matched = candidates[candidate_position]
                    fallback_matched[candidates_key] = (
                        candidate_position + 1
                    )
            if matched is not None:
                matched.asset_id = asset.id

        for block in media_blocks:
            if block.block_type == "code":
                continue

            key = (
                block.page_no,
                block.block_type,
                self.bbox_x1(block.bbox),
            )
            if key in explicit_keys or block.asset_id:
                continue

            metadata = {}
            asset_type = normalize_asset_type(block.block_type)
            if block.block_type == "table" and block.html_table:
                metadata["html"] = block.html_table
            if block.block_type == "formula" and block.latex:
                metadata["latex"] = block.latex
            if block.content_text:
                metadata.setdefault("text", block.content_text)

            promoted = DocumentAsset(
                id=generate_id(),
                document_id=document_id,
                page_no=block.page_no,
                asset_type=asset_type,
                file_path=None,
                caption_text=(
                    block.content_text[:500]
                    if block.content_text
                    else None
                ),
                bbox=block.bbox,
                metadata_json=metadata or None,
            )
            self.db.add(promoted)
            block.asset_id = promoted.id

        await self.db.flush()

    async def persist_blocks(
        self,
        document_id: str,
        blocks: List[ParsedBlock],
    ) -> None:
        """Replace normalized document blocks for a reparsed document."""
        await self.db.execute(
            delete(DocumentBlock).where(
                DocumentBlock.document_id == document_id
            )
        )
        await self.db.flush()

        for block_data in blocks:
            content_text = clean_block_text(block_data.content_text)
            content_md = clean_block_text(block_data.content_md)
            if content_md and content_md == content_text:
                content_md = None
            self.db.add(
                DocumentBlock(
                    id=generate_id(),
                    document_id=document_id,
                    page_no=block_data.page_no,
                    block_type=block_data.block_type,
                    order_no=block_data.order_no,
                    content_text=content_text,
                    content_md=content_md,
                    bbox=block_data.bbox,
                    html_table=block_data.html_table,
                    latex=block_data.latex,
                )
            )

        await self.db.flush()

    async def get_document_detail(
        self,
        document_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return a document with normalized pages, blocks, and assets."""
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            return None

        pages_result = await self.db.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_no)
        )
        pages = [
            {
                "id": page.id,
                "page_no": page.page_no,
                "width": page.width,
                "height": page.height,
            }
            for page in pages_result.scalars().all()
        ]

        blocks_result = await self.db.execute(
            select(DocumentBlock)
            .where(DocumentBlock.document_id == document_id)
            .order_by(DocumentBlock.page_no, DocumentBlock.order_no)
        )
        blocks = [
            {
                "id": block.id,
                "page_no": block.page_no,
                "block_type": block.block_type,
                "order_no": block.order_no,
                "content_text": block.content_text,
                "content_md": block.content_md,
                "html_table": block.html_table,
                "latex": block.latex,
                "bbox": block.bbox,
                "review_status": block.review_status,
            }
            for block in blocks_result.scalars().all()
        ]

        assets_result = await self.db.execute(
            select(DocumentAsset)
            .where(DocumentAsset.document_id == document_id)
            .order_by(DocumentAsset.page_no)
        )
        assets = [
            {
                "id": asset.id,
                "page_no": asset.page_no,
                "asset_type": asset.asset_type,
                "caption_text": asset.caption_text,
                "file_path": asset.file_path,
                "bbox": asset.bbox,
                "metadata": asset.metadata_json,
                "file_url": (
                    f"/api/v1/admin/assets/{asset.id}/file"
                    if asset.file_path
                    else None
                ),
            }
            for asset in assets_result.scalars().all()
        ]

        return {
            "id": document.id,
            "corpus_file_id": document.corpus_file_id,
            "title": document.title,
            "doc_type": document.doc_type,
            "subject_id": document.subject_id,
            "source_label": document.source_label,
            "page_count": document.page_count,
            "latest_parse_run_id": document.latest_parse_run_id,
            "document_markdown": document.document_markdown,
            "document_json": document.document_json,
            "raw_parser_output": document.raw_parser_output,
            "status": document.status,
            "created_at": (
                document.created_at.isoformat()
                if document.created_at
                else None
            ),
            "updated_at": (
                document.updated_at.isoformat()
                if document.updated_at
                else None
            ),
            "pages": pages,
            "blocks": blocks,
            "assets": assets,
        }
