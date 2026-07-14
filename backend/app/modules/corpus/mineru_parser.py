"""Embedded MinerU parser adapter and output normalization."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from app.modules.corpus.parser_types import (
    ParsedAsset,
    ParsedBlock,
    ParsedDocumentResult,
    ParsedPage,
    ParserUnavailableError,
)

logger = get_logger(__name__)


def _ensure_mineru_runtime_defaults() -> None:
    if not os.getenv("MINERU_PDF_RENDER_THREADS"):
        os.environ["MINERU_PDF_RENDER_THREADS"] = "1"
    if not os.getenv("MINERU_PDF_RENDER_TIMEOUT"):
        os.environ["MINERU_PDF_RENDER_TIMEOUT"] = "600"
    if not os.getenv("MINERU_PROCESSING_WINDOW_SIZE"):
        os.environ["MINERU_PROCESSING_WINDOW_SIZE"] = "1"


def _patch_mineru_pdf_rendering() -> None:
    try:
        import mineru.utils.pdf_image_tools as pdf_image_tools  # type: ignore
    except Exception:
        return

    if getattr(pdf_image_tools, "_starmap_single_process_render_patch", False):
        return

    def _load_images_from_pdf_bytes_range_single_process(
        pdf_bytes: bytes,
        dpi=pdf_image_tools.DEFAULT_PDF_IMAGE_DPI,
        start_page_id=0,
        end_page_id=0,
        image_type=pdf_image_tools.ImageType.PIL,
        timeout=None,
        threads=None,
    ):
        if end_page_id < start_page_id:
            return []
        return pdf_image_tools.load_images_from_pdf_core(
            pdf_bytes,
            dpi=dpi,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
            image_type=image_type,
        )

    pdf_image_tools._load_images_from_pdf_bytes_range = (  # type: ignore[attr-defined]
        _load_images_from_pdf_bytes_range_single_process
    )
    pdf_image_tools._starmap_single_process_render_patch = True  # type: ignore[attr-defined]


def normalize_mineru_block_type(item_type: str) -> str:
    mapping = {
        "title": "title",
        "heading": "heading",
        "text": "paragraph",
        "paragraph": "paragraph",
        "list": "list",
        "table": "table",
        "image": "figure",
        "figure": "figure",
        "chart": "figure",
        "equation": "formula",
        "formula": "formula",
        "code": "code",
        "code_block": "code",
        "header": "header",
        "footer": "footer",
        "page_number": "page_number",
        "aside_text": "aside_text",
        "page_footnote": "page_footnote",
    }
    return mapping.get(item_type, "paragraph")


class MinerUParser:
    name = "mineru"
    version = "3.x"

    def parse(self, file_path: str) -> ParsedDocumentResult:
        """Parse a document with the installed MinerU package."""
        _ensure_mineru_runtime_defaults()
        _patch_mineru_pdf_rendering()
        legacy_converter = None
        do_parse = None
        try:
            from mineru.cli.common import convert_single_pdf as legacy_converter  # type: ignore
        except Exception:
            legacy_converter = None

        try:
            from mineru.cli.common import do_parse  # type: ignore
        except Exception:
            do_parse = None

        if legacy_converter is None and do_parse is None:  # pragma: no cover
            raise ParserUnavailableError(
                self.name,
                "mineru 未安装或当前版本接口不兼容，请先安装并验证 MinerU 本地可用",
            )

        with tempfile.TemporaryDirectory(prefix="mineru_parse_") as temp_dir:
            output_dir = Path(temp_dir)
            result: Any = None

            if legacy_converter is not None:
                result = legacy_converter(  # type: ignore[misc]
                    pdf_path=file_path,
                    output_dir=str(output_dir),
                )
            else:
                pdf_name = Path(file_path).name
                pdf_bytes = Path(file_path).read_bytes()
                do_parse(  # type: ignore[misc]
                    output_dir=str(output_dir),
                    pdf_file_names=[pdf_name],
                    pdf_bytes_list=[pdf_bytes],
                    p_lang_list=[""],
                    backend="pipeline",
                    parse_method="auto",
                    formula_enable=True,
                    table_enable=True,
                    f_draw_layout_bbox=False,
                    f_draw_span_bbox=False,
                    f_dump_md=True,
                    f_dump_middle_json=False,
                    f_dump_model_output=False,
                    f_dump_orig_pdf=False,
                    f_dump_content_list=True,
                    image_analysis=True,
                    client_side_output_generation=False,
                )

            return self._normalize_result(
                file_path=file_path,
                result=result,
                output_dir=output_dir,
            )

    @staticmethod
    def _find_content_list(output_dir: Path) -> tuple:
        """Find MinerU's content_list JSON in its generated directory."""
        for pattern in ("*content_list.json", "content_list.json", "**_content_list.json"):
            for path in output_dir.rglob(pattern):
                try:
                    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
                    if isinstance(data, list) and data:
                        return data, path
                except Exception:
                    continue
        return [], None

    @staticmethod
    def _normalize_bbox(bbox: Any) -> Optional[dict]:
        if not bbox:
            return None
        if isinstance(bbox, dict):
            return dict(bbox)
        if isinstance(bbox, (list, tuple)):
            values = [value for value in bbox if isinstance(value, (int, float))]
            if len(values) < 4:
                return None
            x_values = values[::2]
            y_values = values[1::2]
            return {
                "x1": float(x_values[0]) if x_values else None,
                "y1": float(y_values[0]) if y_values else None,
                "x2": (
                    float(x_values[1])
                    if len(x_values) > 1
                    else float(x_values[0])
                ),
                "y2": (
                    float(y_values[1])
                    if len(y_values) > 1
                    else float(y_values[0])
                ),
            }
        return None

    def _normalize_result(
        self,
        file_path: str,
        result: Any,
        output_dir: Path,
    ) -> ParsedDocumentResult:
        pages: List[ParsedPage] = []
        blocks: List[ParsedBlock] = []
        assets: List[ParsedAsset] = []
        document_markdown = ""

        content_list, content_list_path = self._find_content_list(output_dir)
        if isinstance(result, dict):
            fallback = result.get("content_list") or result.get("content_list_json") or []
            if isinstance(fallback, list) and fallback:
                content_list = fallback

        asset_root = content_list_path.parent if content_list_path else output_dir
        order_counters: Dict[int, int] = {}
        for item in content_list:
            if not isinstance(item, dict):
                continue
            page_no = (
                int(item.get("page_idx", 0) or 0) + 1
                if item.get("page_idx") is not None
                else int(item.get("page_no", 1) or 1)
            )
            order_no = order_counters.get(page_no, 0)
            order_counters[page_no] = order_no + 1

            item_type = str(
                item.get("type") or item.get("category") or "paragraph"
            ).lower()
            block_type = normalize_mineru_block_type(item_type)
            bbox = self._normalize_bbox(item.get("bbox"))
            text = item.get("text") or item.get("content") or ""
            markdown = item.get("markdown") or item.get("md") or None

            image_path = (
                item.get("image_path")
                or item.get("img_path")
                or item.get("file_path")
            )
            caption = item.get("caption")
            if caption is None and item_type == "table":
                caption = self._first_caption(item.get("table_caption"))
            elif caption is None and item_type == "image":
                caption = self._first_caption(item.get("image_caption"))

            if block_type in {"figure", "table", "code"}:
                assets.append(
                    ParsedAsset(
                        page_no=page_no,
                        asset_type=block_type,
                        caption_text=caption or text or None,
                        bbox=bbox,
                        file_path=image_path,
                    )
                )

            block_text = text or None
            if not block_text and block_type in {"figure", "table"}:
                block_text = caption or None

            blocks.append(
                ParsedBlock(
                    page_no=page_no,
                    block_type=block_type,
                    order_no=order_no,
                    content_text=block_text,
                    content_md=(
                        markdown
                        if markdown and markdown != text
                        else None
                    ),
                    bbox=bbox,
                    html_table=(
                        item.get("html") or item.get("table_body")
                        if block_type == "table"
                        else None
                    ),
                    latex=item.get("latex") if block_type == "formula" else None,
                )
            )

        if isinstance(result, dict) and result.get("page_count"):
            page_count = int(result["page_count"])
            pages = [ParsedPage(page_no=index + 1) for index in range(page_count)]
        if not pages:
            max_page_no = max((block.page_no for block in blocks), default=0)
            if max_page_no > 0:
                pages = [
                    ParsedPage(page_no=index + 1)
                    for index in range(max_page_no)
                ]

        if isinstance(result, dict):
            markdown_path = result.get("markdown_path") or result.get("md_path")
            if markdown_path and Path(markdown_path).exists():
                document_markdown = Path(markdown_path).read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
        if not document_markdown:
            for markdown_file in output_dir.rglob("*.md"):
                document_markdown = markdown_file.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
                break

        self._inline_asset_images(assets, asset_root)

        return ParsedDocumentResult(
            parser_name=self.name,
            parser_version=self.version,
            pages=pages,
            blocks=blocks,
            assets=assets,
            document_markdown=document_markdown,
            metadata={"source_file": file_path},
            raw_output={
                "content_list": content_list,
                "page_count": len(pages),
                "parser": self.name,
                "parser_version": self.version,
            },
        )

    @staticmethod
    def _first_caption(value: Any) -> Optional[str]:
        if isinstance(value, list):
            return value[0] if value else None
        return value if isinstance(value, str) else None

    @staticmethod
    def _inline_asset_images(assets: List[ParsedAsset], output_dir: Path) -> None:
        for asset in assets:
            raw_path = asset.file_path
            if not raw_path:
                continue

            source = Path(raw_path)
            if source.is_absolute():
                candidates = [source, *list(output_dir.rglob(source.name))]
            else:
                candidates = [
                    output_dir / raw_path,
                    output_dir / "images" / source.name,
                    *list(output_dir.rglob(source.name)),
                ]

            source_path = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.exists() and candidate.is_file()
                ),
                None,
            )
            if not source_path:
                logger.warning("资产图片源文件未找到，跳过", raw_path=raw_path)
                asset.file_path = None
                continue

            try:
                asset.image_base64 = base64.b64encode(
                    source_path.read_bytes()
                ).decode("ascii")
                asset.image_ext = source_path.suffix or ".png"
            except Exception as exc:
                logger.warning(
                    "资产图片读取失败",
                    src=str(source_path),
                    error=str(exc),
                )
            asset.file_path = None
