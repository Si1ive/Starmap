"""
独立 PDF 解析服务

职责：
1. 在独立容器中提供 `/health` 与 `/parse` 接口
2. 使用本地已安装的 Docling / MinerU 依赖执行解析
3. 将解析结果标准化返回给主 backend
"""

from __future__ import annotations

from contextlib import contextmanager
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.core.logging import configure_logging, get_logger
from app.services.document_parsers import (
    ParsedAsset,
    ParsedBlock,
    ParsedDocumentResult,
    ParsedPage,
    ParserUnavailableError,
    get_parser,
    get_supported_parser_names,
    inspect_parser_health,
)

logger = get_logger(__name__)
_MINERU_RUNTIME_LOCK = threading.Lock()

APP_VERSION = "1.0.0"
DEFAULT_PARSER = os.getenv("PDF_PARSER_SERVICE_DEFAULT", "mineru").strip().lower() or "mineru"

app = FastAPI(
    title="StarMap PDF Parser Service",
    description="独立 PDF 解析服务，供主 backend 通过 HTTP 调用",
    version=APP_VERSION,
)


@app.on_event("startup")
async def startup_event() -> None:
    configure_logging()
    logger.info(
        "PDF 解析服务启动完成",
        default_parser=DEFAULT_PARSER,
        supported_parsers=get_supported_parser_names(),
    )


def _resolve_parser_name(parser_name: Optional[str]) -> str:
    normalized = (parser_name or DEFAULT_PARSER).strip().lower()
    if normalized not in {"docling", "mineru"}:
        raise HTTPException(status_code=400, detail=f"不支持的解析器: {parser_name}")
    return normalized


def _serialize_parse_result(result: ParsedDocumentResult) -> Dict[str, Any]:
    return {
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
        "pages": [_serialize_page(page) for page in result.pages],
        "blocks": [_serialize_block(block) for block in result.blocks],
        "assets": [_serialize_asset(asset) for asset in result.assets],
        "document_markdown": result.document_markdown,
        "confidence": result.confidence,
        "metadata": result.metadata or {},
        "page_count": result.page_count,
        "block_count": result.block_count,
        "asset_count": result.asset_count,
        "raw_output": result.raw_output,
    }


def _serialize_page(page: ParsedPage) -> Dict[str, Any]:
    return {
        "page_no": page.page_no,
        "width": page.width,
        "height": page.height,
    }


def _serialize_block(block: ParsedBlock) -> Dict[str, Any]:
    return {
        "page_no": block.page_no,
        "block_type": block.block_type,
        "order_no": block.order_no,
        "content_text": block.content_text,
        "content_md": block.content_md,
        "bbox": block.bbox,
        "html_table": block.html_table,
        "latex": block.latex,
    }


def _serialize_asset(asset: ParsedAsset) -> Dict[str, Any]:
    return {
        "page_no": asset.page_no,
        "asset_type": asset.asset_type,
        "caption_text": asset.caption_text,
        "bbox": asset.bbox,
        "file_path": asset.file_path,
    }


@contextmanager
def _temporary_mineru_processing_window_size(value: Optional[int]):
    if value is None:
        yield
        return

    normalized = max(1, int(value))
    with _MINERU_RUNTIME_LOCK:
        original = os.getenv("MINERU_PROCESSING_WINDOW_SIZE")
        os.environ["MINERU_PROCESSING_WINDOW_SIZE"] = str(normalized)
        try:
            yield
        finally:
            if original is None:
                os.environ.pop("MINERU_PROCESSING_WINDOW_SIZE", None)
            else:
                os.environ["MINERU_PROCESSING_WINDOW_SIZE"] = original


@app.get("/health")
async def health_check(parser_name: Optional[str] = None) -> Dict[str, Any]:
    normalized = _resolve_parser_name(parser_name)
    health = inspect_parser_health(
        normalized,
        {
            "active_parser": normalized,
            "deployment_target": "embedded",
        },
    )
    health["service_mode"] = "standalone_http"
    health["default_parser"] = DEFAULT_PARSER
    return {
        "code": 200,
        "message": "success",
        "data": health,
    }


@app.post("/parse")
async def parse_document(
    file: UploadFile = File(...),
    parser_name: Optional[str] = Form(default=None),
    processing_window_size: Optional[int] = Form(default=None),
) -> Dict[str, Any]:
    normalized = _resolve_parser_name(parser_name)
    suffix = Path(file.filename or "document.pdf").suffix or ".pdf"

    try:
        parser = get_parser(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        with tempfile.TemporaryDirectory(prefix="parser_service_") as temp_dir:
            temp_path = Path(temp_dir) / f"input{suffix}"
            temp_path.write_bytes(await file.read())
            with _temporary_mineru_processing_window_size(
                processing_window_size if normalized == "mineru" else None
            ):
                result = parser.parse(str(temp_path))
            payload = _serialize_parse_result(result)
            payload["metadata"] = {
                **(payload.get("metadata") or {}),
                "source_filename": file.filename,
                "service_parser": normalized,
                **(
                    {"processing_window_size": processing_window_size}
                    if normalized == "mineru" and processing_window_size is not None
                    else {}
                ),
            }
            return {
                "code": 200,
                "message": "success",
                "data": payload,
            }
    except ParserUnavailableError as exc:
        logger.error("解析器不可用", parser_name=normalized, error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.error("解析服务运行时失败", parser_name=normalized, error=str(exc))
        raise HTTPException(status_code=500, detail=f"解析失败: {str(exc)[:200]}") from exc
    except Exception as exc:
        logger.error("解析服务未知异常", parser_name=normalized, error=str(exc))
        raise HTTPException(status_code=500, detail=f"解析失败: {str(exc)[:200]}") from exc


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": "pdf-parser-service",
        "version": APP_VERSION,
        "default_parser": DEFAULT_PARSER,
        "supported_parsers": get_supported_parser_names(),
        "health": "/health",
        "parse": "/parse",
    }
