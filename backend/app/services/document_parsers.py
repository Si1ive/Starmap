"""
文档解析器适配层

目标：
1. 屏蔽 Docling / MinerU 原始输出差异
2. 统一向 DocumentParseService 提供标准化解析结果
3. 支持后端按请求或策略切换解析器
"""

from __future__ import annotations

import base64
import inspect
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import urlparse

import requests

from app.core.logging import get_logger
from app.core.config import settings

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


class ParserUnavailableError(RuntimeError):
    """解析器依赖未就绪或当前服务不可用。"""

    def __init__(self, parser_name: str, detail: str):
        self.parser_name = parser_name
        self.detail = detail
        super().__init__(detail)


@dataclass
class ParsedPage:
    page_no: int
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class ParsedBlock:
    page_no: int
    block_type: str
    order_no: int
    content_text: Optional[str] = None
    content_md: Optional[str] = None
    bbox: Optional[dict] = None
    html_table: Optional[str] = None
    latex: Optional[str] = None


@dataclass
class ParsedAsset:
    page_no: int
    asset_type: str = "figure"
    caption_text: Optional[str] = None
    bbox: Optional[dict] = None
    file_path: Optional[str] = None
    # 临时字段：解析阶段把图片字节读成 base64 内联传输（不入库）。
    # parser_service（podman 容器）与主 backend 不共享文件系统，图片字节必须
    # 随 JSON 内联回传，由主 backend 统一解码落盘到 uploads/assets。
    image_base64: Optional[str] = None
    image_ext: Optional[str] = None


@dataclass
class ParsedDocumentResult:
    parser_name: str
    parser_version: str
    pages: List[ParsedPage]
    blocks: List[ParsedBlock]
    assets: List[ParsedAsset]
    document_markdown: str = ""
    confidence: Optional[float] = None
    metadata: Optional[dict] = None
    raw_output: Optional[dict] = None  # 解析器原始输出

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def asset_count(self) -> int:
        return len(self.assets)


class DocumentParser(Protocol):
    name: str
    version: str

    def parse(self, file_path: str) -> ParsedDocumentResult:
        ...


@dataclass
class PdfParserRuntimeConfig:
    active_parser: str
    deployment_target: str
    local_service_endpoint: str
    remote_service_endpoint: str
    request_timeout_seconds: int
    processing_window_size: Optional[int] = None


BLOCK_TYPE_MAP = {
    "Title": "title",
    "TitleItem": "title",
    "TITLE": "title",
    "Heading": "heading",
    "SectionHeaderItem": "heading",
    "SECTION_HEADER": "heading",
    "Paragraph": "paragraph",
    "TextItem": "paragraph",
    "TEXT": "paragraph",
    "PARAGRAPH": "paragraph",
    "REFERENCE": "paragraph",
    "HANDWRITTEN_TEXT": "paragraph",
    "ListItem": "list",
    "List": "list",
    "LIST_ITEM": "list",
    "Table": "table",
    "TableItem": "table",
    "TABLE": "table",
    "DOCUMENT_INDEX": "table",
    "TableCaption": "table_caption",
    "Picture": "figure",
    "Figure": "figure",
    "PictureItem": "figure",
    "PICTURE": "figure",
    "CHART": "figure",
    "FigureCaption": "figure_caption",
    "Equation": "formula",
    "FormulaItem": "formula",
    "FORMULA": "formula",
    "CodeBlock": "code",
    "CodeItem": "code",
    "CODE": "code",
    "PageBreak": "unknown",
}


def _map_docling_block_type(docling_type: str) -> str:
    return BLOCK_TYPE_MAP.get(docling_type, "paragraph")


def _resolve_docling_type(item: Any) -> str:
    candidates = [type(item).__name__]
    label = getattr(item, "label", None)
    if label is not None:
        label_value = getattr(label, "value", None)
        if label_value:
            candidates.append(str(label_value))
            candidates.append(str(label_value).upper())
        candidates.append(str(label))

    for candidate in candidates:
        mapped = BLOCK_TYPE_MAP.get(candidate)
        if mapped:
            return mapped
    return "paragraph"


def _extract_page_no(item: Any) -> int:
    if hasattr(item, "prov") and item.prov:
        prov = item.prov
        if isinstance(prov, list) and len(prov) > 0:
            return getattr(prov[0], "page_no", 1) or 1
        return getattr(prov, "page_no", 1) or 1
    return 1


def _extract_bbox(item: Any) -> Optional[dict]:
    if hasattr(item, "prov") and item.prov:
        prov = item.prov
        if isinstance(prov, list) and len(prov) > 0:
            prov = prov[0]
        if hasattr(prov, "bbox") and prov.bbox:
            box = prov.bbox
            return {
                "l": getattr(box, "l", None),
                "t": getattr(box, "t", None),
                "r": getattr(box, "r", None),
                "b": getattr(box, "b", None),
            }
    return None


def _extract_text(item: Any, doc: Any = None) -> str:
    if hasattr(item, "text") and item.text:
        return item.text
    caption_text = getattr(item, "caption_text", None)
    if callable(caption_text) and doc is not None:
        try:
            text = caption_text(doc)
            if text:
                return text
        except Exception:
            pass
    if hasattr(item, "caption") and item.caption:
        return item.caption
    return ""


def _call_docling_export(item: Any, method_name: str, doc: Any = None) -> str:
    method = getattr(item, method_name, None)
    if not callable(method):
        return ""

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        signature = None

    try:
        if signature is not None and len(signature.parameters) >= 1 and doc is not None:
            return method(doc)
        return method()
    except Exception:
        return ""


def _extract_md(item: Any, doc: Any = None) -> str:
    markdown = _call_docling_export(item, "export_to_markdown", doc)
    if markdown:
        return markdown
    return _extract_text(item, doc)


def _iterate_docling_items(doc: Any) -> List[Any]:
    iterate_items = getattr(doc, "iterate_items", None)
    if callable(iterate_items):
        return [item for item, _ in iterate_items(with_groups=False, traverse_pictures=True)]

    body = getattr(doc, "body", None)
    if body is None:
        return []

    walk = getattr(body, "walk", None)
    if callable(walk):
        return list(walk())

    return []


def _export_docling_markdown(doc: Any) -> str:
    exporter = getattr(doc, "export_to_markdown", None)
    if not callable(exporter):
        return ""

    try:
        return exporter(traverse_pictures=True)
    except TypeError:
        try:
            return exporter()
        except Exception:
            return ""
    except Exception:
        return ""


class DoclingParser:
    name = "docling"
    version = "2.x"

    def parse(self, file_path: str) -> ParsedDocumentResult:
        try:
            from docling.document_converter import DocumentConverter
        except Exception as exc:
            raise ParserUnavailableError(
                self.name,
                "docling 未安装或当前版本接口不兼容，请先安装并验证 Docling 本地可用"
            ) from exc

        converter = DocumentConverter()
        result = converter.convert(file_path)
        doc = result.document

        pages: List[ParsedPage] = []
        for index, page in enumerate(getattr(doc, "pages", []) or []):
            page_no = index + 1
            width = getattr(page, "width", None) or getattr(page, "size", None)
            height = getattr(page, "height", None)
            if hasattr(page, "size") and page.size:
                width = getattr(page.size, "width", width)
                height = getattr(page.size, "height", height)
            pages.append(
                ParsedPage(
                    page_no=page_no,
                    width=int(width) if width else None,
                    height=int(height) if height else None,
                )
            )

        blocks: List[ParsedBlock] = []
        assets: List[ParsedAsset] = []
        order_counters: Dict[int, int] = {}
        for item in _iterate_docling_items(doc):
            block_type = _resolve_docling_type(item)
            page_no = _extract_page_no(item)
            order_no = order_counters.get(page_no, 0)
            order_counters[page_no] = order_no + 1

            content_text = _extract_text(item, doc) or None
            content_md = _extract_md(item, doc)

            block = ParsedBlock(
                page_no=page_no,
                block_type=block_type,
                order_no=order_no,
                content_text=content_text,
                content_md=content_md if content_md and content_md != content_text else None,
                bbox=_extract_bbox(item),
            )

            if block_type == "table":
                html_table = _call_docling_export(item, "export_to_html", doc)
                if html_table:
                    block.html_table = html_table

            if block_type == "formula" and hasattr(item, "text"):
                block.latex = getattr(item, "text", None)

            if block_type in {"figure", "table"}:
                assets.append(
                    ParsedAsset(
                        page_no=page_no,
                        asset_type=block_type,
                        caption_text=content_text,
                        bbox=block.bbox,
                    )
                )

            blocks.append(block)

        document_markdown = _export_docling_markdown(doc)

        # Docling 的原始输出是对象，我们转换为可序列化的字典
        raw_output = None
        try:
            # 尝试导出为JSON格式，仅保留核心结构信息
            raw_output = {
                "parser": self.name,
                "parser_version": self.version,
                "page_count": len(pages),
                "items_count": len(blocks),
                # Docling 对象太大，只保留元数据
                "metadata": {
                    "has_pages": bool(pages),
                    "has_body": hasattr(doc, "body"),
                },
            }
        except Exception:
            pass

        return ParsedDocumentResult(
            parser_name=self.name,
            parser_version=self.version,
            pages=pages,
            blocks=blocks,
            assets=assets,
            document_markdown=document_markdown,
            metadata={"source_file": file_path},
            raw_output=raw_output,
        )


class MinerUParser:
    name = "mineru"
    version = "3.x"

    def parse(self, file_path: str) -> ParsedDocumentResult:
        """
        MinerU 适配器。

        当前实现优先兼容已安装的 python 包；若环境未安装，则抛出清晰错误。
        这里统一输出 ParsedDocumentResult，下游不感知 MinerU 原始结构。
        """
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

        if legacy_converter is None and do_parse is None:  # pragma: no cover - 依赖环境相关
            raise ParserUnavailableError(
                self.name,
                "mineru 未安装或当前版本接口不兼容，请先安装并验证 MinerU 本地可用"
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

            normalized = self._normalize_result(file_path=file_path, result=result, output_dir=output_dir)
            return normalized

    @staticmethod
    def _find_content_list(output_dir: Path) -> tuple:
        """
        从 MinerU 输出目录寻找 content_list.json。

        do_parse 把产出写到 output_dir/<pdf_name>/auto/ 子目录，
        result dict 不包含 content_list 字段。这里直接搜磁盘。

        Returns (content_list, file_path) —— file_path 用于下游推断 auto_dir。
        """
        # content_list.json / *_content_list.json 两种命名
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
        """归一化 bbox 为字典，兼容 dict、list/tuple、其他类型。"""
        if not bbox:
            return None
        if isinstance(bbox, dict):
            return dict(bbox)
        if isinstance(bbox, (list, tuple)):
            values = [v for v in bbox if isinstance(v, (int, float))]
            if len(values) < 4:
                return None
            x_values = values[::2]
            y_values = values[1::2]
            return {
                "x1": float(x_values[0]) if x_values else None,
                "y1": float(y_values[0]) if y_values else None,
                "x2": float(x_values[1]) if len(x_values) > 1 else float(x_values[0]),
                "y2": float(y_values[1]) if len(y_values) > 1 else float(y_values[0]),
            }
        return None

    def _normalize_result(
        self,
        file_path: str,
        result: Any,
        output_dir: Path,
    ) -> ParsedDocumentResult:
        """
        将 MinerU 输出适配成统一结构。

        MinerU do_parse 产出全部落在 output_dir 磁盘上（content_list、md、图片），
        result dict 几乎没有有效字段。适配层统一从磁盘读取。
        """
        pages: List[ParsedPage] = []
        blocks: List[ParsedBlock] = []
        assets: List[ParsedAsset] = []
        document_markdown = ""

        # ---- content_list: 仅从磁盘读取（do_parse 不返回在 result dict 中） ----
        content_list, cl_path = self._find_content_list(output_dir)
        if isinstance(result, dict):
            fallback = result.get("content_list") or result.get("content_list_json") or []
            if isinstance(fallback, list) and fallback:
                content_list = fallback

        # ---- MinerU 图片/表格真实输出根目录（content_list 中 image_path 以此为基础） ----
        # content_list 在 output_dir/<pdf>/auto/ 下，图片也在同级的 images/ 子目录
        auto_dir = output_dir
        if cl_path:
            auto_dir = cl_path.parent  # .../<pdf>/auto/

        # ---- blocks / assets ----
        order_counters: Dict[int, int] = {}
        for item in content_list:
            if not isinstance(item, dict):
                continue
            page_no = int(item.get("page_idx", 0) or 0) + 1 if item.get("page_idx") is not None else int(item.get("page_no", 1) or 1)
            order_no = order_counters.get(page_no, 0)
            order_counters[page_no] = order_no + 1

            item_type = str(item.get("type") or item.get("category") or "paragraph").lower()
            block_type = self._map_mineru_block_type(item_type)
            bbox = self._normalize_bbox(item.get("bbox"))
            text = item.get("text") or item.get("content") or ""
            md = item.get("markdown") or item.get("md") or None

            image_path = item.get("image_path") or item.get("img_path") or item.get("file_path")
            caption = item.get("caption")
            if caption is None:
                if item_type == "table":
                    table_caption = item.get("table_caption")
                    if isinstance(table_caption, list):
                        caption = table_caption[0] if table_caption else None
                    elif isinstance(table_caption, str):
                        caption = table_caption
                elif item_type == "image":
                    image_caption = item.get("image_caption")
                    if isinstance(image_caption, list):
                        caption = image_caption[0] if image_caption else None
                    elif isinstance(image_caption, str):
                        caption = image_caption

            # MinerU 的 content_list 会把图片用 type="image" 表示；映射后应归类到 figure。
            # 这里按已映射类型判断是为了确保图像资产不会被遗漏。
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

            # 图片/表格块：若 MinerU 未给 text 字段，用 caption 作为 content_text，
            # 避免落库后 figure block 内容为空。
            block_text = text or None
            if not block_text and block_type in {"figure", "table"}:
                block_text = caption or None

            blocks.append(
                ParsedBlock(
                    page_no=page_no,
                    block_type=block_type,
                    order_no=order_no,
                    content_text=block_text,
                    content_md=md if md and md != text else None,
                    bbox=bbox,
                    html_table=item.get("html") or item.get("table_body") if block_type == "table" else None,
                    latex=item.get("latex") if block_type == "formula" else None,
                )
            )

        # ---- pages ----
        if isinstance(result, dict) and result.get("page_count"):
            page_count = int(result["page_count"])
            pages = [ParsedPage(page_no=i + 1) for i in range(page_count)]
        if not pages:
            max_page_no = max((block.page_no for block in blocks), default=0)
            if max_page_no > 0:
                pages = [ParsedPage(page_no=i + 1) for i in range(max_page_no)]

        # ---- markdown ----
        if isinstance(result, dict):
            md_path = result.get("markdown_path") or result.get("md_path")
            if md_path and Path(md_path).exists():
                document_markdown = Path(md_path).read_text(encoding="utf-8", errors="ignore")
        if not document_markdown:
            for md in output_dir.rglob("*.md"):
                document_markdown = md.read_text(encoding="utf-8", errors="ignore")
                break

        # ---- 图片 base64 内联 ----
        # MinerU 的 image 产出在 auto_dir/images/ 下，
        # content_list 中的 image_path 相对于 auto_dir。
        self._inline_asset_images(assets, auto_dir)

        raw_output = {
            "content_list": content_list,
            "page_count": len(pages),
            "parser": self.name,
            "parser_version": self.version,
        }

        return ParsedDocumentResult(
            parser_name=self.name,
            parser_version=self.version,
            pages=pages,
            blocks=blocks,
            assets=assets,
            document_markdown=document_markdown,
            metadata={"source_file": file_path},
            raw_output=raw_output,
        )

    @staticmethod
    def _inline_asset_images(assets: List[ParsedAsset], output_dir: Path) -> None:
        """
        把 MinerU 写在临时目录里的图片读成 base64，内联到 asset.image_base64。

        MinerU 的图片产出在 output_dir（tempfile）内，解析结束临时目录销毁后即失效。
        嵌入模式下主 backend 直接拿到内存对象，服务模式下 base64 随 JSON 跨进程回传，
        两种模式统一由主 backend 的 _persist_assets 写盘到 uploads/assets/，
        file_path 由主 backend 生成，确保始终是主 backend 可读的 host 路径。
        """
        for asset in assets:
            raw = asset.file_path
            if not raw:
                continue

            # MinerU 的 image_path 可能是相对（相对 output_dir）或绝对路径
            src = Path(raw)
            if not src.is_absolute():
                candidates = [
                    output_dir / raw,
                    output_dir / "images" / src.name,
                    *list(output_dir.rglob(src.name)),
                ]
            else:
                candidates = [src, *list(output_dir.rglob(src.name))]

            src_path = next((c for c in candidates if c.exists() and c.is_file()), None)
            if not src_path:
                logger.warning("资产图片源文件未找到，跳过", raw_path=raw)
                asset.file_path = None
                continue

            try:
                asset.image_base64 = base64.b64encode(src_path.read_bytes()).decode("ascii")
                asset.image_ext = src_path.suffix or ".png"
            except Exception as e:
                logger.warning("资产图片读取失败", src=str(src_path), error=str(e))
            # file_path 是临时路径，跨进程/临时目录销毁后无意义，清空交由主 backend 重建
            asset.file_path = None

    @staticmethod
    def _map_mineru_block_type(item_type: str) -> str:
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


class LocalParserServiceClient:
    def __init__(
        self,
        parser_name: str,
        endpoint: str,
        timeout_seconds: int,
        processing_window_size: Optional[int] = None,
    ):
        self.name = parser_name
        self.version = "service"
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.processing_window_size = processing_window_size

    def parse(self, file_path: str, task_id: Optional[str] = None) -> ParsedDocumentResult:
        if not self.endpoint:
            raise ParserUnavailableError(
                self.name,
                "未配置本地解析服务地址，请在系统设置中确认本地 Podman 解析服务配置",
            )

        try:
            with open(file_path, "rb") as file_obj:
                response = requests.post(
                    f"{self.endpoint}/parse",
                    data={
                        "parser_name": self.name,
                        **(
                            {"processing_window_size": str(self.processing_window_size)}
                            if self.name == "mineru" and self.processing_window_size
                            else {}
                        ),
                        **({"task_id": task_id} if task_id else {}),
                    },
                    files={"file": (Path(file_path).name, file_obj, "application/pdf")},
                    timeout=self.timeout_seconds,
                )
        except requests.RequestException as exc:
            raise ParserUnavailableError(
                self.name,
                f"无法连接本地解析服务 {self.endpoint}：{str(exc)[:200]}",
            ) from exc

        if response.status_code >= 400:
            detail = _extract_service_error_detail(response)
            raise ParserUnavailableError(
                self.name,
                f"本地解析服务返回异常（HTTP {response.status_code}）：{detail}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ParserUnavailableError(
                self.name,
                f"本地解析服务返回了无效 JSON：{response.text[:200]}",
            ) from exc

        normalized = _unwrap_service_payload(payload)
        return _parsed_document_result_from_dict(
            parser_name=self.name,
            payload=normalized,
            fallback_metadata={"source_file": file_path, "service_endpoint": self.endpoint},
        )

    def fetch_progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询解析进度（主 backend 轮询用），失败返回 None 不抛异常。"""
        if not self.endpoint or not task_id:
            return None
        try:
            response = requests.get(f"{self.endpoint}/progress/{task_id}", timeout=5)
            if response.status_code != 200:
                return None
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            return data if isinstance(data, dict) else None
        except Exception:
            return None


class RemoteParserServiceClient:
    def __init__(self, parser_name: str, endpoint: str, timeout_seconds: int):
        self.name = parser_name
        self.version = "service"
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def parse(self, file_path: str) -> ParsedDocumentResult:
        raise ParserUnavailableError(
            self.name,
            (
                f"已配置远程解析服务 {self.endpoint}，但当前版本尚未实现远程解析调用链路。"
                " 当前仅保留配置结构和扩展口，请先切回本地解析服务模式。"
            ),
        )


def _normalize_runtime_config(runtime_config: Optional[Dict[str, Any]] = None) -> PdfParserRuntimeConfig:
    config = runtime_config or {}
    active_parser = str(config.get("active_parser") or "mineru").strip().lower()
    if active_parser not in {"docling", "mineru"}:
        active_parser = "mineru"

    deployment_target = str(config.get("deployment_target") or "local").strip().lower()
    if deployment_target not in {"local", "remote", "embedded"}:
        deployment_target = "local"

    timeout_seconds = int(config.get("request_timeout_seconds") or 600)
    if timeout_seconds < 5:
        timeout_seconds = 5
    if timeout_seconds > 1800:
        timeout_seconds = 1800

    processing_window_size = config.get("processing_window_size")
    if processing_window_size is not None:
        try:
            processing_window_size = int(processing_window_size)
        except (TypeError, ValueError):
            processing_window_size = None
    if processing_window_size is not None and processing_window_size < 1:
        processing_window_size = 1

    local_endpoint = str(
        config.get("local_service_endpoint") or settings.PDF_PARSER_LOCAL_ENDPOINT
    ).strip()
    remote_endpoint = str(config.get("remote_service_endpoint") or "").strip()

    return PdfParserRuntimeConfig(
        active_parser=active_parser,
        deployment_target=deployment_target,
        local_service_endpoint=local_endpoint,
        remote_service_endpoint=remote_endpoint,
        request_timeout_seconds=timeout_seconds,
        processing_window_size=processing_window_size,
    )


def _extract_service_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] or "未知错误"

    if isinstance(payload, dict):
        if isinstance(payload.get("detail"), str):
            return payload["detail"][:200]
        if isinstance(payload.get("message"), str):
            return payload["message"][:200]
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("detail"), str):
            return data["detail"][:200]
    return str(payload)[:200]


def _unwrap_service_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    if isinstance(payload, dict):
        return payload
    raise ParserUnavailableError("unknown", "解析服务返回结构不符合约定")


def _normalize_asset_type(raw_asset_type: Optional[Any]) -> str:
    """Normalize raw asset type to DB-safe enum values."""
    value = (str(raw_asset_type).strip().lower() if raw_asset_type is not None else "figure")
    if not value:
        return "figure"
    if value in {"figure", "table", "formula", "page_crop", "other"}:
        return value
    if value in {"img", "image", "picture", "chart"}:
        return "figure"
    if value in {"eq", "formula_block", "equation", "formula_img"}:
        return "formula"
    # 兼容服务/模型返回的未知类型
    return "other"


def _normalize_payload_block_type(raw_block_type: Optional[Any]) -> str:
    """Normalize block_type from parser payload to internal block type set."""
    value = (str(raw_block_type or "").strip().lower())
    if not value:
        return "paragraph"

    if value in {"image", "img", "picture", "chart"}:
        return "figure"
    if value in {"paragraph", "text"}:
        return "paragraph"
    if value in {
        "heading", "title", "table", "figure", "formula", "code", "code_block", "list",
        "header", "footer", "page_number", "aside_text", "page_footnote",
    }:
        return value if value != "code_block" else "code"
    if value == "equation":
        return "formula"

    # 兼容历史输入：未显式提供 block_type 时，尝试按 payload type/category 原始语义归一。
    return _map_mineru_block_type(value)


def _parsed_document_result_from_dict(
    parser_name: str,
    payload: Dict[str, Any],
    fallback_metadata: Optional[Dict[str, Any]] = None,
) -> ParsedDocumentResult:
    pages = [
        ParsedPage(
            page_no=int(item.get("page_no") or 1),
            width=int(item["width"]) if item.get("width") is not None else None,
            height=int(item["height"]) if item.get("height") is not None else None,
        )
        for item in (payload.get("pages") or [])
        if isinstance(item, dict)
    ]
    blocks = [
        ParsedBlock(
            page_no=int(item.get("page_no") or 1),
            block_type=_normalize_payload_block_type(
                item.get("type") or item.get("category") or item.get("block_type")
            ),
            order_no=int(item.get("order_no") or 0),
            content_text=item.get("content_text"),
            content_md=item.get("content_md"),
            bbox=item.get("bbox") if isinstance(item.get("bbox"), dict) else None,
            html_table=item.get("html_table"),
            latex=item.get("latex"),
        )
        for item in (payload.get("blocks") or [])
        if isinstance(item, dict)
    ]
    assets = [
        ParsedAsset(
            page_no=int(item.get("page_no") or 1),
            asset_type=_normalize_asset_type(item.get("asset_type")),
            caption_text=item.get("caption_text"),
            bbox=item.get("bbox") if isinstance(item.get("bbox"), dict) else None,
            file_path=item.get("file_path"),
            image_base64=item.get("image_base64"),
            image_ext=item.get("image_ext"),
        )
        for item in (payload.get("assets") or [])
        if isinstance(item, dict)
    ]

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if fallback_metadata:
        metadata = {**fallback_metadata, **metadata}

    # 优先使用解析服务透传的解析器原始输出（含 MinerU content_list 等）；
    # 旧版服务未透传时，回退到整个标准化 payload，保证页级对比仍有数据可看。
    raw_output = payload.get("raw_output")
    if not isinstance(raw_output, dict):
        raw_output = payload

    return ParsedDocumentResult(
        parser_name=str(payload.get("parser_name") or parser_name),
        parser_version=str(payload.get("parser_version") or "service"),
        pages=pages,
        blocks=blocks,
        assets=assets,
        document_markdown=str(payload.get("document_markdown") or ""),
        confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
        metadata=metadata,
        raw_output=raw_output,
    )


def _is_valid_url(value: str) -> bool:
    parsed = urlparse((value or "").strip())
    return bool(parsed.scheme and parsed.netloc)


def get_parser(parser_name: str) -> DocumentParser:
    normalized = (parser_name or "").strip().lower()
    if normalized == "docling":
        return DoclingParser()
    if normalized == "mineru":
        return MinerUParser()
    raise ValueError(f"不支持的解析器: {parser_name}")


def get_supported_parser_names() -> List[str]:
    return ["docling", "mineru"]


def inspect_parser_health(
    parser_name: str,
    runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized = (parser_name or "").strip().lower()
    config = _normalize_runtime_config(runtime_config)
    checked_at = datetime.utcnow().isoformat()

    if config.deployment_target == "embedded":
        parser = get_parser(normalized)
        try:
            if normalized == "docling":
                from docling.document_converter import DocumentConverter

                _ = DocumentConverter
            elif normalized == "mineru":
                try:
                    from mineru.cli.common import convert_single_pdf  # type: ignore

                    _ = convert_single_pdf
                except Exception:
                    from mineru.cli.common import do_parse  # type: ignore

                    _ = do_parse

            return {
                "parser_name": parser.name,
                "parser_version": parser.version,
                "health_status": "ready",
                "is_available": True,
                "checked_at": checked_at,
                "deployment_target": "embedded",
                "service_endpoint": None,
                "error_detail": None,
            }
        except Exception as exc:
            return {
                "parser_name": parser.name,
                "parser_version": parser.version,
                "health_status": "unavailable",
                "is_available": False,
                "checked_at": checked_at,
                "deployment_target": "embedded",
                "service_endpoint": None,
                "error_detail": str(exc)[:200],
            }

    service_endpoint = (
        config.local_service_endpoint
        if config.deployment_target == "local"
        else config.remote_service_endpoint
    )

    if config.deployment_target == "remote":
        return {
            "parser_name": normalized,
            "parser_version": "service",
            "health_status": "unavailable",
            "is_available": False,
            "checked_at": checked_at,
            "deployment_target": "remote",
            "service_endpoint": service_endpoint,
            "error_detail": (
                f"远程解析服务地址已配置为 {service_endpoint}"
                if service_endpoint
                else "尚未配置远程解析服务地址"
            )
            + "，但当前版本尚未实现远程探活与远程解析调用链路。",
        }

    if not service_endpoint:
        return {
            "parser_name": normalized,
            "parser_version": "service",
            "health_status": "unavailable",
            "is_available": False,
            "checked_at": checked_at,
            "deployment_target": "local",
            "service_endpoint": service_endpoint,
            "error_detail": "未配置本地解析服务地址，请在系统设置或环境变量中补充",
        }

    try:
        response = requests.get(
            f"{service_endpoint.rstrip('/')}/health",
            params={"parser_name": normalized},
            timeout=min(config.request_timeout_seconds, 10),
        )
        if response.status_code >= 400:
            detail = _extract_service_error_detail(response)
            return {
                "parser_name": normalized,
                "parser_version": "service",
                "health_status": "unavailable",
                "is_available": False,
                "checked_at": checked_at,
                "deployment_target": "local",
                "service_endpoint": service_endpoint,
                "error_detail": f"本地解析服务探活失败（HTTP {response.status_code}）：{detail}",
            }

        payload = response.json() if response.content else {}
        data = _unwrap_service_payload(payload) if payload else {}
        return {
            "parser_name": str(data.get("parser_name") or normalized),
            "parser_version": str(data.get("parser_version") or "service"),
            "health_status": str(data.get("health_status") or "ready"),
            "is_available": bool(data.get("is_available", True)),
            "checked_at": str(data.get("checked_at") or checked_at),
            "deployment_target": "local",
            "service_endpoint": service_endpoint,
            "error_detail": data.get("error_detail"),
        }
    except requests.RequestException as exc:
        return {
            "parser_name": normalized,
            "parser_version": "service",
            "health_status": "unavailable",
            "is_available": False,
            "checked_at": checked_at,
            "deployment_target": "local",
            "service_endpoint": service_endpoint,
            "error_detail": f"无法连接本地解析服务 {service_endpoint}：{str(exc)[:200]}",
        }
    except Exception as exc:
        return {
            "parser_name": normalized,
            "parser_version": "service",
            "health_status": "unavailable",
            "is_available": False,
            "checked_at": checked_at,
            "deployment_target": "local",
            "service_endpoint": service_endpoint,
            "error_detail": f"本地解析服务探活返回异常：{str(exc)[:200]}",
        }


def choose_parser(
    requested_parser: Optional[str],
    runtime_config: Optional[Dict[str, Any]] = None,
) -> DocumentParser:
    """
    解析器选择策略。

    当前策略：
    - 运行时只激活一个主解析器
    - 指定 parser 时直接使用
    - 部署目标为 local 时，调用本地 Podman 解析服务
    - 部署目标为 remote 时，保留远程扩展口
    """
    config = _normalize_runtime_config(runtime_config)
    parser_name = (requested_parser or config.active_parser or "mineru").strip().lower()
    if parser_name not in {"docling", "mineru"}:
        raise ValueError(f"不支持的解析器: {parser_name}")

    if config.deployment_target == "local":
        return LocalParserServiceClient(
            parser_name=parser_name,
            endpoint=config.local_service_endpoint,
            timeout_seconds=config.request_timeout_seconds,
            processing_window_size=config.processing_window_size,
        )

    if config.deployment_target == "remote":
        if not config.remote_service_endpoint:
            raise ParserUnavailableError(
                parser_name,
                "当前已切换到远程解析服务模式，但尚未配置远程服务地址",
            )
        if not _is_valid_url(config.remote_service_endpoint):
            raise ParserUnavailableError(
                parser_name,
                f"远程解析服务地址格式不合法：{config.remote_service_endpoint}",
            )
        return RemoteParserServiceClient(
            parser_name=parser_name,
            endpoint=config.remote_service_endpoint,
            timeout_seconds=config.request_timeout_seconds,
        )

    raise ValueError(f"不支持的部署目标: {config.deployment_target}")
