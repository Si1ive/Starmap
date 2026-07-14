"""MinerU PDF 解析服务的运行配置规则。"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.modules.operations.system_settings_rules import default_system_settings


@dataclass(frozen=True)
class PdfParserUpdatePlan:
    """一次 MinerU 运行配置更新的确定性执行计划。"""

    previous_config: Dict[str, Any]
    next_config: Dict[str, Any]
    old_audit_values: Dict[str, Any]
    new_audit_values: Dict[str, Any]
    is_switching: bool
    should_audit: bool
    requires_local_health_check: bool


def build_pdf_parser_runtime_config(data: Any) -> Dict[str, Any]:
    """补齐运行配置并强制使用 MinerU。"""
    defaults = default_system_settings()["pdf_parser"]
    merged = copy.deepcopy(defaults)
    if isinstance(data, dict):
        merged.update(copy.deepcopy(data))
    merged["active_parser"] = "mineru"
    merged["service_mode"] = "mineru_only"
    return merged


def prepare_pdf_parser_update(
    current_config: Any,
    *,
    parser_name: str,
    deployment_target: str = "local",
    local_service_endpoint: Optional[str] = None,
    remote_service_endpoint: Optional[str] = None,
    request_timeout_seconds: Optional[int] = None,
    processing_window_size: Optional[int] = None,
    switch_notes: str = "",
) -> PdfParserUpdatePlan:
    """校验输入并生成 MinerU 配置更新计划。"""
    normalized = str(parser_name).strip().lower()
    if normalized != "mineru":
        raise ValueError("PDF 解析器已固定为 mineru")

    target = str(deployment_target or "local").strip().lower()
    if target not in {"local", "remote"}:
        raise ValueError("pdf_parser.deployment_target 仅支持 local 或 remote")

    defaults = default_system_settings()["pdf_parser"]
    previous = (
        copy.deepcopy(current_config)
        if isinstance(current_config, dict)
        else {}
    )
    old_parser = previous.get("active_parser", "")
    old_target = previous.get("deployment_target", "local")
    old_local_endpoint = previous.get(
        "local_service_endpoint",
        defaults["local_service_endpoint"],
    )
    old_remote_endpoint = previous.get("remote_service_endpoint", "")
    old_timeout = int(
        previous.get(
            "request_timeout_seconds",
            defaults["request_timeout_seconds"],
        )
    )
    old_processing_window_size = int(
        previous.get(
            "processing_window_size",
            defaults["processing_window_size"],
        )
    )

    next_local_endpoint = (
        str(local_service_endpoint).strip()
        if local_service_endpoint is not None
        else str(old_local_endpoint or defaults["local_service_endpoint"]).strip()
    )
    next_remote_endpoint = (
        str(remote_service_endpoint).strip()
        if remote_service_endpoint is not None
        else str(old_remote_endpoint or "").strip()
    )
    next_timeout = int(request_timeout_seconds or old_timeout or 600)
    if next_timeout < 5 or next_timeout > 600:
        raise ValueError("pdf_parser.request_timeout_seconds 仅支持 5-600 秒")

    next_processing_window_size = int(
        processing_window_size
        or previous.get(
            "processing_window_size",
            defaults["processing_window_size"],
        )
        or defaults["processing_window_size"]
    )
    if next_processing_window_size < 1 or next_processing_window_size > 64:
        raise ValueError("pdf_parser.processing_window_size 仅支持 1-64")

    is_switching = (
        normalized != old_parser
        or target != old_target
        or next_local_endpoint != str(old_local_endpoint or "")
        or next_remote_endpoint != str(old_remote_endpoint or "")
        or next_timeout != old_timeout
        or next_processing_window_size != old_processing_window_size
    )
    notes = (switch_notes or "").strip()
    if is_switching and not notes:
        raise ValueError(
            "切换 PDF 解析器或部署位置必须填写切换备注，说明原因、部署步骤和回滚方案"
        )

    if target == "remote":
        if not next_remote_endpoint:
            raise ValueError("远程解析服务模式必须填写 remote_service_endpoint")
        parsed = urlparse(next_remote_endpoint)
        if not (parsed.scheme and parsed.netloc):
            raise ValueError("remote_service_endpoint 地址格式不合法，需包含协议和主机")

    next_config = {
        "active_parser": "mineru",
        "service_mode": "mineru_only",
        "service_switch_notes": notes,
        "deployment_target": target,
        "local_service_endpoint": next_local_endpoint,
        "remote_service_endpoint": next_remote_endpoint,
        "request_timeout_seconds": next_timeout,
        "processing_window_size": next_processing_window_size,
    }
    old_audit_values = {
        "active_parser": old_parser,
        "deployment_target": old_target,
        "local_service_endpoint": old_local_endpoint,
        "remote_service_endpoint": old_remote_endpoint,
        "request_timeout_seconds": old_timeout,
        "processing_window_size": old_processing_window_size,
    }
    new_audit_values = {
        "active_parser": normalized,
        "deployment_target": target,
        "local_service_endpoint": next_local_endpoint,
        "remote_service_endpoint": next_remote_endpoint,
        "request_timeout_seconds": next_timeout,
        "processing_window_size": next_processing_window_size,
        "switch_notes": notes,
    }
    return PdfParserUpdatePlan(
        previous_config=previous,
        next_config=next_config,
        old_audit_values=old_audit_values,
        new_audit_values=new_audit_values,
        is_switching=is_switching,
        should_audit=is_switching or bool(notes),
        requires_local_health_check=is_switching and target == "local",
    )
