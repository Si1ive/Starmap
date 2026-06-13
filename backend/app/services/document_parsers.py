"""
文档解析器适配层

目标：
1. 屏蔽 Docling / MinerU 原始输出差异
2. 统一向 DocumentParseService 提供标准化解析结果
3. 支持后端按请求或策略切换解析器
"""

from __future__ import annotations

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


BLOCK_TYPE_MAP = {
    "Title": "title",
    "Heading": "heading",
    "Paragraph": "paragraph",
    "ListItem": "list",
    "List": "list",
    "Table": "table",
    "TableCaption": "table_caption",
    "Picture": "figure",
    "Figure": "figure",
    "FigureCaption": "figure_caption",
    "Equation": "formula",
    "CodeBlock": "code",
    "PageBreak": "unknown",
}


def _map_docling_block_type(docling_type: str) -> str:
    return BLOCK_TYPE_MAP.get(docling_type, "paragraph")


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


def _extract_text(item: Any) -> str:
    if hasattr(item, "text") and item.text:
        return item.text
    if hasattr(item, "caption") and item.caption:
        return item.caption
    return ""


def _extract_md(item: Any) -> str:
    if hasattr(item, "export_to_markdown"):
        try:
            return item.export_to_markdown()
        except Exception:
            pass
    return _extract_text(item)


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
        order_counters: Dict[int, int] = {}
        if hasattr(doc, "body") and doc.body:
            for item in doc.body.walk():
                docling_type = type(item).__name__
                page_no = _extract_page_no(item)
                order_no = order_counters.get(page_no, 0)
                order_counters[page_no] = order_no + 1

                block = ParsedBlock(
                    page_no=page_no,
                    block_type=_map_docling_block_type(docling_type),
                    order_no=order_no,
                    content_text=_extract_text(item),
                    content_md=None,
                    bbox=_extract_bbox(item),
                )

                md = _extract_md(item)
                if md != block.content_text:
                    block.content_md = md

                if docling_type == "Table" and hasattr(item, "export_to_html"):
                    try:
                        block.html_table = item.export_to_html()
                    except Exception:
                        pass

                if docling_type == "Equation" and hasattr(item, "text"):
                    block.latex = getattr(item, "text", None)

                blocks.append(block)

        assets: List[ParsedAsset] = []
        if hasattr(doc, "pictures"):
            for pic in doc.pictures:
                page_no = 1
                caption = ""
                if hasattr(pic, "prov") and pic.prov:
                    prov = pic.prov[0] if isinstance(pic.prov, list) and pic.prov else pic.prov
                    page_no = getattr(prov, "page_no", 1) or 1
                if hasattr(pic, "caption"):
                    caption = pic.caption or ""
                elif hasattr(pic, "text"):
                    caption = pic.text or ""

                assets.append(
                    ParsedAsset(
                        page_no=page_no,
                        asset_type="figure",
                        caption_text=caption,
                        bbox=_extract_bbox(pic),
                    )
                )

        document_markdown = ""
        if hasattr(doc, "export_to_markdown"):
            try:
                document_markdown = doc.export_to_markdown()
            except Exception:
                pass

        return ParsedDocumentResult(
            parser_name=self.name,
            parser_version=self.version,
            pages=pages,
            blocks=blocks,
            assets=assets,
            document_markdown=document_markdown,
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
        try:
            from mineru.cli.common import convert_single_pdf  # type: ignore
        except Exception as exc:  # pragma: no cover - 依赖环境相关
            raise ParserUnavailableError(
                self.name,
                "mineru 未安装或当前版本接口不兼容，请先安装并验证 MinerU 本地可用"
            ) from exc

        with tempfile.TemporaryDirectory(prefix="mineru_parse_") as temp_dir:
            output_dir = Path(temp_dir)
            result = convert_single_pdf(  # type: ignore
                pdf_path=file_path,
                output_dir=str(output_dir),
            )

            normalized = self._normalize_result(file_path=file_path, result=result, output_dir=output_dir)
            return normalized

    def _normalize_result(
        self,
        file_path: str,
        result: Any,
        output_dir: Path,
    ) -> ParsedDocumentResult:
        """
        将 MinerU 输出适配成统一结构。

        说明：
        - MinerU 原始输出结构与版本关系较大
        - 适配层只负责尽可能提取 page/block/asset/markdown
        - 若字段缺失，保持为空，不影响下游库表结构
        """
        pages: List[ParsedPage] = []
        blocks: List[ParsedBlock] = []
        assets: List[ParsedAsset] = []
        document_markdown = ""

        if isinstance(result, dict):
            markdown_path = result.get("markdown_path") or result.get("md_path")
            if markdown_path and Path(markdown_path).exists():
                document_markdown = Path(markdown_path).read_text(encoding="utf-8", errors="ignore")

            content_list = result.get("content_list") or result.get("content_list_json") or []
            if isinstance(content_list, list):
                order_counters: Dict[int, int] = {}
                for item in content_list:
                    page_no = int(item.get("page_idx", 0) or 0) + 1 if item.get("page_idx") is not None else int(item.get("page_no", 1) or 1)
                    order_no = order_counters.get(page_no, 0)
                    order_counters[page_no] = order_no + 1

                    item_type = str(item.get("type") or item.get("category") or "paragraph").lower()
                    block_type = self._map_mineru_block_type(item_type)
                    bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else None
                    text = item.get("text") or item.get("content") or ""
                    md = item.get("markdown") or item.get("md") or None

                    if block_type in {"figure", "table"}:
                        assets.append(
                            ParsedAsset(
                                page_no=page_no,
                                asset_type=block_type,
                                caption_text=item.get("caption") or text or None,
                                bbox=bbox,
                                file_path=item.get("image_path") or item.get("file_path"),
                            )
                        )

                    blocks.append(
                        ParsedBlock(
                            page_no=page_no,
                            block_type=block_type,
                            order_no=order_no,
                            content_text=text or None,
                            content_md=md if md and md != text else None,
                            bbox=bbox,
                            html_table=item.get("html") if block_type == "table" else None,
                            latex=item.get("latex") if block_type == "formula" else None,
                        )
                    )

            page_count = int(result.get("page_count") or 0)
            if page_count > 0:
                pages = [ParsedPage(page_no=index + 1) for index in range(page_count)]

        if not pages:
            max_page_no = max((block.page_no for block in blocks), default=0)
            if max_page_no > 0:
                pages = [ParsedPage(page_no=index + 1) for index in range(max_page_no)]

        if not document_markdown:
            markdown_candidates = list(output_dir.rglob("*.md"))
            if markdown_candidates:
                document_markdown = markdown_candidates[0].read_text(encoding="utf-8", errors="ignore")

        return ParsedDocumentResult(
            parser_name=self.name,
            parser_version=self.version,
            pages=pages,
            blocks=blocks,
            assets=assets,
            document_markdown=document_markdown,
            metadata={"source_file": file_path},
        )

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
            "equation": "formula",
            "formula": "formula",
            "code": "code",
        }
        return mapping.get(item_type, "paragraph")


class LocalParserServiceClient:
    def __init__(self, parser_name: str, endpoint: str, timeout_seconds: int):
        self.name = parser_name
        self.version = "service"
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def parse(self, file_path: str) -> ParsedDocumentResult:
        if not self.endpoint:
            raise ParserUnavailableError(
                self.name,
                "未配置本地解析服务地址，请在系统设置中确认本地 Podman 解析服务配置",
            )

        try:
            with open(file_path, "rb") as file_obj:
                response = requests.post(
                    f"{self.endpoint}/parse",
                    data={"parser_name": self.name},
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

    timeout_seconds = int(config.get("request_timeout_seconds") or 120)
    if timeout_seconds < 5:
        timeout_seconds = 5

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
            block_type=str(item.get("block_type") or "paragraph"),
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
            asset_type=str(item.get("asset_type") or "figure"),
            caption_text=item.get("caption_text"),
            bbox=item.get("bbox") if isinstance(item.get("bbox"), dict) else None,
            file_path=item.get("file_path"),
        )
        for item in (payload.get("assets") or [])
        if isinstance(item, dict)
    ]

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if fallback_metadata:
        metadata = {**fallback_metadata, **metadata}

    return ParsedDocumentResult(
        parser_name=str(payload.get("parser_name") or parser_name),
        parser_version=str(payload.get("parser_version") or "service"),
        pages=pages,
        blocks=blocks,
        assets=assets,
        document_markdown=str(payload.get("document_markdown") or ""),
        confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
        metadata=metadata,
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
                from mineru.cli.common import convert_single_pdf  # type: ignore

                _ = convert_single_pdf

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
