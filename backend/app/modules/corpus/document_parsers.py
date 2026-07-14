"""
MinerU 文档解析适配层

目标：
1. 屏蔽 MinerU 原始输出差异
2. 统一向 DocumentParseService 提供标准化解析结果
3. 支持嵌入、本地服务和远程服务三种部署方式
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from app.core.config import settings
from app.modules.corpus.mineru_parser import (
    MinerUParser,
    normalize_mineru_block_type,
)
from app.modules.corpus.parser_types import (
    DocumentParser,
    ParsedAsset,
    ParsedBlock,
    ParsedDocumentResult,
    ParsedPage,
    ParserUnavailableError,
    PdfParserRuntimeConfig,
)

class HttpParserServiceClient:
    def __init__(
        self,
        parser_name: str,
        endpoint: str,
        timeout_seconds: int,
        deployment_target: str,
        processing_window_size: Optional[int] = None,
    ):
        self.name = parser_name
        self.version = "service"
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.deployment_target = deployment_target
        self.processing_window_size = processing_window_size

    @property
    def _target_label(self) -> str:
        return "远程" if self.deployment_target == "remote" else "本地"

    def parse(self, file_path: str, task_id: Optional[str] = None) -> ParsedDocumentResult:
        if not self.endpoint:
            raise ParserUnavailableError(
                self.name,
                f"未配置{self._target_label}解析服务地址，请在系统设置中确认解析服务配置",
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
                f"无法连接{self._target_label}解析服务 {self.endpoint}：{str(exc)[:200]}",
            ) from exc

        if response.status_code >= 400:
            detail = _extract_service_error_detail(response)
            raise ParserUnavailableError(
                self.name,
                f"{self._target_label}解析服务返回异常（HTTP {response.status_code}）：{detail}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ParserUnavailableError(
                self.name,
                f"{self._target_label}解析服务返回了无效 JSON：{response.text[:200]}",
            ) from exc

        normalized = _unwrap_service_payload(payload)
        return _parsed_document_result_from_dict(
            parser_name=self.name,
            payload=normalized,
            fallback_metadata={
                "source_file": file_path,
                "service_endpoint": self.endpoint,
                "deployment_target": self.deployment_target,
            },
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


class LocalParserServiceClient(HttpParserServiceClient):
    def __init__(
        self,
        parser_name: str,
        endpoint: str,
        timeout_seconds: int,
        processing_window_size: Optional[int] = None,
    ):
        super().__init__(
            parser_name=parser_name,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            deployment_target="local",
            processing_window_size=processing_window_size,
        )


class RemoteParserServiceClient(HttpParserServiceClient):
    def __init__(
        self,
        parser_name: str,
        endpoint: str,
        timeout_seconds: int,
        processing_window_size: Optional[int] = None,
    ):
        super().__init__(
            parser_name=parser_name,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            deployment_target="remote",
            processing_window_size=processing_window_size,
        )


def _normalize_runtime_config(runtime_config: Optional[Dict[str, Any]] = None) -> PdfParserRuntimeConfig:
    config = runtime_config or {}

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
        active_parser="mineru",
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
    return normalize_mineru_block_type(value)


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
    if normalized == "mineru":
        return MinerUParser()
    raise ValueError(f"不支持的解析器: {parser_name}")


def get_supported_parser_names() -> List[str]:
    return ["mineru"]


def inspect_parser_health(
    parser_name: str,
    runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized = (parser_name or "").strip().lower()
    config = _normalize_runtime_config(runtime_config)
    checked_at = datetime.now(timezone.utc).isoformat()

    if config.deployment_target == "embedded":
        parser = get_parser(normalized)
        try:
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

    target_label = "远程" if config.deployment_target == "remote" else "本地"

    if not service_endpoint:
        return {
            "parser_name": normalized,
            "parser_version": "service",
            "health_status": "unavailable",
            "is_available": False,
            "checked_at": checked_at,
            "deployment_target": config.deployment_target,
            "service_endpoint": service_endpoint,
            "error_detail": f"未配置{target_label}解析服务地址，请在系统设置或环境变量中补充",
        }

    if not _is_valid_url(service_endpoint):
        return {
            "parser_name": normalized,
            "parser_version": "service",
            "health_status": "unavailable",
            "is_available": False,
            "checked_at": checked_at,
            "deployment_target": config.deployment_target,
            "service_endpoint": service_endpoint,
            "error_detail": f"{target_label}解析服务地址格式不合法：{service_endpoint}",
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
                "deployment_target": config.deployment_target,
                "service_endpoint": service_endpoint,
                "error_detail": f"{target_label}解析服务探活失败（HTTP {response.status_code}）：{detail}",
            }

        payload = response.json() if response.content else {}
        data = _unwrap_service_payload(payload) if payload else {}
        return {
            "parser_name": str(data.get("parser_name") or normalized),
            "parser_version": str(data.get("parser_version") or "service"),
            "health_status": str(data.get("health_status") or "ready"),
            "is_available": bool(data.get("is_available", True)),
            "checked_at": str(data.get("checked_at") or checked_at),
            "deployment_target": config.deployment_target,
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
            "deployment_target": config.deployment_target,
            "service_endpoint": service_endpoint,
            "error_detail": f"无法连接{target_label}解析服务 {service_endpoint}：{str(exc)[:200]}",
        }
    except Exception as exc:
        return {
            "parser_name": normalized,
            "parser_version": "service",
            "health_status": "unavailable",
            "is_available": False,
            "checked_at": checked_at,
            "deployment_target": config.deployment_target,
            "service_endpoint": service_endpoint,
            "error_detail": f"{target_label}解析服务探活返回异常：{str(exc)[:200]}",
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
    - 部署目标为 remote 时，调用远程 HTTP 解析服务
    """
    config = _normalize_runtime_config(runtime_config)
    parser_name = (requested_parser or "mineru").strip().lower()
    if parser_name != "mineru":
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
            processing_window_size=config.processing_window_size,
        )

    raise ValueError(f"不支持的部署目标: {config.deployment_target}")
