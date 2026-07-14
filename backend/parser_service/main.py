"""
独立 PDF 解析服务

职责：
1. 在独立容器中提供 `/health` 与 `/parse` 接口
2. 使用本地已安装的 Docling / MinerU 依赖执行解析
3. 将解析结果标准化返回给主 backend
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.core.logging import configure_logging, get_logger
from app.modules.corpus.document_parsers import (
    get_parser,
    get_supported_parser_names,
    inspect_parser_health,
)
from app.modules.corpus.parser_types import (
    ParsedAsset,
    ParsedBlock,
    ParsedDocumentResult,
    ParsedPage,
    ParserUnavailableError,
)

logger = get_logger(__name__)
_MINERU_RUNTIME_LOCK = threading.Lock()

APP_VERSION = "1.0.0"
DEFAULT_PARSER = os.getenv("PDF_PARSER_SERVICE_DEFAULT", "mineru").strip().lower() or "mineru"

# ========== 解析进度追踪 ==========
# MinerU 解析被 _MINERU_RUNTIME_LOCK 串行化，同一时刻最多一个任务在跑，
# 因此用 _CURRENT_TASK_ID 标记当前任务，日志拦截器据此归属页码进度。
_PROGRESS: Dict[str, Dict[str, Any]] = {}
_PROGRESS_LOCK = threading.Lock()
_CURRENT_TASK_ID: Optional[str] = None

# 匹配 MinerU 日志中的页码进度。
# 真实日志关键行（loguru INFO）：
#   "Pipeline processing window batch 2/11: 2/11 pages, batch_pages=1, ..."
#   "Pipeline ... multi-file run. doc_count=1, total_pages=11, window_size=1, total_batches=11"
# 注意：tqdm 的 "Processing pages: 18%|..| 2/11" 直接写 stderr，不走 loguru/logging，拦不到。
_PAGE_PATTERNS = [
    re.compile(r'batch\s+(\d+)\s*/\s*(\d+)', re.IGNORECASE),       # "batch 2/11" —— 最可靠
    re.compile(r'(\d+)\s*/\s*(\d+)\s*pages', re.IGNORECASE),       # "2/11 pages"
    re.compile(r'page[^\d]{0,6}(\d+)\s*/\s*(\d+)', re.IGNORECASE),
]
# 仅含总页数的行（用于尽早确定 total_pages）
_TOTAL_PAGES_PATTERN = re.compile(r'total_pages[=:\s]+(\d+)', re.IGNORECASE)


def _record_progress_from_text(text: str) -> None:
    """从一行日志文本里提取页码并写入当前任务的进度。"""
    global _CURRENT_TASK_ID
    task_id = _CURRENT_TASK_ID
    if not task_id:
        return
    lower = text.lower()
    if "page" not in lower and "batch" not in lower:
        return

    # 先尝试更新总页数（"total_pages=11"）
    tm = _TOTAL_PAGES_PATTERN.search(text)
    if tm:
        total = int(tm.group(1))
        with _PROGRESS_LOCK:
            entry = _PROGRESS.get(task_id)
            if entry is not None and total:
                entry["total_pages"] = total
                entry["updated_at"] = time.time()

    for pattern in _PAGE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        current_page = int(m.group(1))
        total_pages = int(m.group(2)) if len(m.groups()) > 1 else None
        with _PROGRESS_LOCK:
            entry = _PROGRESS.get(task_id)
            if entry is not None:
                entry["current_page"] = current_page
                if total_pages:
                    entry["total_pages"] = total_pages
                entry["updated_at"] = time.time()
        return


class _StdLoggingProgressHandler(logging.Handler):
    """标准 logging 拦截器（兜底，若 MinerU 用 logging 而非 loguru）。"""

    def emit(self, record):
        try:
            _record_progress_from_text(record.getMessage())
        except Exception:
            pass


def _install_progress_interceptors() -> None:
    """挂载日志拦截器：loguru sink（MinerU 主用）+ 标准 logging handler（兜底）。"""
    # loguru（新版 MinerU 用 loguru）
    try:
        from loguru import logger as loguru_logger  # type: ignore

        def _loguru_sink(message):
            try:
                _record_progress_from_text(str(message))
            except Exception:
                pass

        loguru_logger.add(_loguru_sink, level="DEBUG")
        logger.info("loguru 进度拦截器已挂载")
    except Exception as exc:
        logger.warning("loguru 拦截器挂载失败（可能未安装 loguru）", error=str(exc))

    # 标准 logging 兜底
    try:
        std_handler = _StdLoggingProgressHandler()
        std_handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        root.addHandler(std_handler)
        logger.info("标准 logging 进度拦截器已挂载")
    except Exception as exc:
        logger.warning("标准 logging 拦截器挂载失败", error=str(exc))


app = FastAPI(
    title="StarMap PDF Parser Service",
    description="独立 PDF 解析服务，供主 backend 通过 HTTP 调用",
    version=APP_VERSION,
)


@app.on_event("startup")
async def startup_event() -> None:
    configure_logging()
    _install_progress_interceptors()
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
        # 图片字节随 JSON 内联回传（容器与主 backend 不共享文件系统）
        "image_base64": asset.image_base64,
        "image_ext": asset.image_ext,
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
    task_id: Optional[str] = Form(default=None),
) -> Dict[str, Any]:
    global _CURRENT_TASK_ID
    normalized = _resolve_parser_name(parser_name)
    suffix = Path(file.filename or "document.pdf").suffix or ".pdf"

    try:
        parser = get_parser(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 初始化进度追踪
    if task_id:
        with _PROGRESS_LOCK:
            _PROGRESS[task_id] = {
                "task_id": task_id,
                "status": "parsing",
                "current_page": 0,
                "total_pages": 0,
                "updated_at": time.time(),
            }
        _CURRENT_TASK_ID = task_id

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
            # 标记进度完成
            if task_id:
                with _PROGRESS_LOCK:
                    entry = _PROGRESS.get(task_id)
                    if entry is not None:
                        entry["status"] = "done"
                        entry["current_page"] = result.page_count or entry.get("current_page", 0)
                        entry["total_pages"] = result.page_count or entry.get("total_pages", 0)
                        entry["updated_at"] = time.time()
            return {
                "code": 200,
                "message": "success",
                "data": payload,
            }
    except ParserUnavailableError as exc:
        logger.error("解析器不可用", parser_name=normalized, error=str(exc))
        if task_id:
            with _PROGRESS_LOCK:
                if task_id in _PROGRESS:
                    _PROGRESS[task_id]["status"] = "failed"
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.error("解析服务运行时失败", parser_name=normalized, error=str(exc))
        if task_id:
            with _PROGRESS_LOCK:
                if task_id in _PROGRESS:
                    _PROGRESS[task_id]["status"] = "failed"
        raise HTTPException(status_code=500, detail=f"解析失败: {str(exc)[:200]}") from exc
    except Exception as exc:
        logger.error("解析服务未知异常", parser_name=normalized, error=str(exc))
        if task_id:
            with _PROGRESS_LOCK:
                if task_id in _PROGRESS:
                    _PROGRESS[task_id]["status"] = "failed"
        raise HTTPException(status_code=500, detail=f"解析失败: {str(exc)[:200]}") from exc
    finally:
        # 清理当前任务标记（保留进度条目供最后一次轮询读取）
        if task_id and _CURRENT_TASK_ID == task_id:
            _CURRENT_TASK_ID = None


@app.get("/progress/{task_id}")
async def get_progress(task_id: str) -> Dict[str, Any]:
    """查询解析进度（主 backend 轮询用）。"""
    with _PROGRESS_LOCK:
        entry = _PROGRESS.get(task_id)
        data = dict(entry) if entry else {"task_id": task_id, "status": "unknown"}
    return {"code": 200, "message": "success", "data": data}


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
