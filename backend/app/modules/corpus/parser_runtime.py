"""MinerU parser runtime selection, configuration, and health inspection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from app.core.config import settings
from app.modules.corpus.mineru_parser import MinerUParser
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

MINERU_PARSER_NAME = "mineru"


def normalize_runtime_config(
    runtime_config: Optional[Dict[str, Any]] = None,
) -> PdfParserRuntimeConfig:
    config = runtime_config or {}

    deployment_target = str(
        config.get("deployment_target") or "local"
    ).strip().lower()
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
        config.get("local_service_endpoint")
        or settings.PDF_PARSER_LOCAL_ENDPOINT
    ).strip()
    remote_endpoint = str(
        config.get("remote_service_endpoint") or ""
    ).strip()

    return PdfParserRuntimeConfig(
        active_parser=MINERU_PARSER_NAME,
        deployment_target=deployment_target,
        local_service_endpoint=local_endpoint,
        remote_service_endpoint=remote_endpoint,
        request_timeout_seconds=timeout_seconds,
        processing_window_size=processing_window_size,
    )


def is_valid_url(value: str) -> bool:
    parsed = urlparse((value or "").strip())
    return bool(parsed.scheme and parsed.netloc)


def validate_mineru_parser_name(parser_name: Optional[str]) -> None:
    """校验兼容字段，但不提供解析器选择能力。"""
    normalized = (parser_name or MINERU_PARSER_NAME).strip().lower()
    if normalized != MINERU_PARSER_NAME:
        raise ValueError("PDF 解析器固定使用 MinerU")


def inspect_mineru_health(
    runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    config = normalize_runtime_config(runtime_config)
    checked_at = datetime.now(timezone.utc).isoformat()

    if config.deployment_target == "embedded":
        parser = MinerUParser()
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
    target_label = (
        "远程" if config.deployment_target == "remote" else "本地"
    )

    if not service_endpoint:
        return {
            "parser_name": MINERU_PARSER_NAME,
            "parser_version": "service",
            "health_status": "unavailable",
            "is_available": False,
            "checked_at": checked_at,
            "deployment_target": config.deployment_target,
            "service_endpoint": service_endpoint,
            "error_detail": (
                f"未配置{target_label}解析服务地址，请在系统设置或环境变量中补充"
            ),
        }

    if not is_valid_url(service_endpoint):
        return {
            "parser_name": MINERU_PARSER_NAME,
            "parser_version": "service",
            "health_status": "unavailable",
            "is_available": False,
            "checked_at": checked_at,
            "deployment_target": config.deployment_target,
            "service_endpoint": service_endpoint,
            "error_detail": (
                f"{target_label}解析服务地址格式不合法：{service_endpoint}"
            ),
        }

    try:
        response = requests.get(
            f"{service_endpoint.rstrip('/')}/health",
            params={"parser_name": MINERU_PARSER_NAME},
            timeout=min(config.request_timeout_seconds, 10),
        )
        if response.status_code >= 400:
            detail = extract_service_error_detail(response)
            return {
                "parser_name": MINERU_PARSER_NAME,
                "parser_version": "service",
                "health_status": "unavailable",
                "is_available": False,
                "checked_at": checked_at,
                "deployment_target": config.deployment_target,
                "service_endpoint": service_endpoint,
                "error_detail": (
                    f"{target_label}解析服务探活失败"
                    f"（HTTP {response.status_code}）：{detail}"
                ),
            }

        payload = response.json() if response.content else {}
        data = unwrap_service_payload(payload) if payload else {}
        return {
            "parser_name": str(
                data.get("parser_name") or MINERU_PARSER_NAME
            ),
            "parser_version": str(
                data.get("parser_version") or "service"
            ),
            "health_status": str(data.get("health_status") or "ready"),
            "is_available": bool(data.get("is_available", True)),
            "checked_at": str(data.get("checked_at") or checked_at),
            "deployment_target": config.deployment_target,
            "service_endpoint": service_endpoint,
            "error_detail": data.get("error_detail"),
        }
    except requests.RequestException as exc:
        return {
            "parser_name": MINERU_PARSER_NAME,
            "parser_version": "service",
            "health_status": "unavailable",
            "is_available": False,
            "checked_at": checked_at,
            "deployment_target": config.deployment_target,
            "service_endpoint": service_endpoint,
            "error_detail": (
                f"无法连接{target_label}解析服务 {service_endpoint}："
                f"{str(exc)[:200]}"
            ),
        }
    except Exception as exc:
        return {
            "parser_name": MINERU_PARSER_NAME,
            "parser_version": "service",
            "health_status": "unavailable",
            "is_available": False,
            "checked_at": checked_at,
            "deployment_target": config.deployment_target,
            "service_endpoint": service_endpoint,
            "error_detail": (
                f"{target_label}解析服务探活返回异常：{str(exc)[:200]}"
            ),
        }


def create_mineru_parser(
    runtime_config: Optional[Dict[str, Any]] = None,
) -> DocumentParser:
    """按配置的部署位置构造 MinerU 适配器。"""
    config = normalize_runtime_config(runtime_config)

    if config.deployment_target == "embedded":
        return MinerUParser()

    if config.deployment_target == "local":
        return LocalParserServiceClient(
            parser_name=MINERU_PARSER_NAME,
            endpoint=config.local_service_endpoint,
            timeout_seconds=config.request_timeout_seconds,
            processing_window_size=config.processing_window_size,
        )

    if config.deployment_target == "remote":
        if not config.remote_service_endpoint:
            raise ParserUnavailableError(
                MINERU_PARSER_NAME,
                "当前已切换到远程解析服务模式，但尚未配置远程服务地址",
            )
        if not is_valid_url(config.remote_service_endpoint):
            raise ParserUnavailableError(
                MINERU_PARSER_NAME,
                f"远程解析服务地址格式不合法：{config.remote_service_endpoint}",
            )
        return RemoteParserServiceClient(
            parser_name=MINERU_PARSER_NAME,
            endpoint=config.remote_service_endpoint,
            timeout_seconds=config.request_timeout_seconds,
            processing_window_size=config.processing_window_size,
        )

    raise ValueError(f"不支持的部署目标: {config.deployment_target}")
