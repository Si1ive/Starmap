"""
MinerU 文档解析适配层

目标：
1. 屏蔽 MinerU 原始输出差异
2. 统一向 DocumentParseService 提供标准化解析结果
3. 支持嵌入、本地服务和远程服务三种部署方式
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from app.core.config import settings
from app.modules.corpus.mineru_parser import (
    MinerUParser,
)
from app.modules.corpus.parser_service_client import (
    LocalParserServiceClient,
    RemoteParserServiceClient,
    extract_service_error_detail,
    unwrap_service_payload,
)
from app.modules.corpus.parser_types import (
    DocumentParser,
    ParserUnavailableError,
    PdfParserRuntimeConfig,
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
            detail = extract_service_error_detail(response)
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
        data = unwrap_service_payload(payload) if payload else {}
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
