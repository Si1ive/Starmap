"""爬虫运行配置的默认值、校验和审计脱敏规则。"""

import copy
import math
from typing import Any, Dict, Optional
from urllib.parse import urlparse


def default_crawler_settings() -> Dict[str, Any]:
    """Return a fresh crawler runtime configuration."""
    return {
        "concurrent_requests": 4,
        "concurrent_requests_per_domain": 2,
        "download_delay_seconds": 1.0,
        "request_timeout_seconds": 60,
        "retry_times": 3,
        "rotate_user_agent": True,
        "user_agent": "408StudyBot/1.0",
        "obey_robots_txt": False,
        "follow_redirects": True,
        "max_redirect_times": 20,
        "max_depth": 5,
        "proxy_enabled": False,
        "proxy_url": "",
        "log_level": "INFO",
    }


def normalize_crawler_settings(
    data: Optional[Dict[str, Any]],
    *,
    reject_unknown: bool = True,
) -> Dict[str, Any]:
    """Validate the crawler settings that the Scrapy runtime can execute."""
    defaults = default_crawler_settings()
    raw = dict(data or {})
    unknown = sorted(set(raw) - set(defaults))
    if reject_unknown and unknown:
        raise ValueError(f"不支持的配置项: {', '.join(unknown)}")

    values = copy.deepcopy(defaults)
    values.update(
        {
            key: value
            for key, value in raw.items()
            if key in defaults
        }
    )

    concurrent_requests = _bounded_int(
        values["concurrent_requests"],
        "crawler.concurrent_requests",
        1,
        64,
    )
    concurrent_per_domain = _bounded_int(
        values["concurrent_requests_per_domain"],
        "crawler.concurrent_requests_per_domain",
        1,
        64,
    )
    if concurrent_per_domain > concurrent_requests:
        raise ValueError(
            "crawler.concurrent_requests_per_domain 不能大于 "
            "concurrent_requests"
        )

    rotate_user_agent = _strict_bool(
        values["rotate_user_agent"],
        "crawler.rotate_user_agent",
    )
    user_agent = str(values["user_agent"] or "").strip()
    if not rotate_user_agent and not user_agent:
        raise ValueError(
            "关闭随机 User-Agent 后必须填写 crawler.user_agent"
        )
    if len(user_agent) > 512:
        raise ValueError("crawler.user_agent 最多支持 512 个字符")

    proxy_enabled = _strict_bool(
        values["proxy_enabled"],
        "crawler.proxy_enabled",
    )
    proxy_url = str(values["proxy_url"] or "").strip()
    if proxy_enabled and not proxy_url:
        raise ValueError("启用代理后必须填写 crawler.proxy_url")
    if proxy_url:
        parsed_proxy = urlparse(proxy_url)
        if parsed_proxy.scheme.lower() not in {"http", "https"}:
            raise ValueError(
                "crawler.proxy_url 仅支持 http 或 https 代理"
            )
        if not parsed_proxy.netloc:
            raise ValueError("crawler.proxy_url 地址格式不合法")

    log_level = str(values["log_level"] or "").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError(
            "crawler.log_level 仅支持 DEBUG、INFO、WARNING 或 ERROR"
        )

    return {
        "concurrent_requests": concurrent_requests,
        "concurrent_requests_per_domain": concurrent_per_domain,
        "download_delay_seconds": _bounded_float(
            values["download_delay_seconds"],
            "crawler.download_delay_seconds",
            0,
            60,
        ),
        "request_timeout_seconds": _bounded_int(
            values["request_timeout_seconds"],
            "crawler.request_timeout_seconds",
            5,
            600,
        ),
        "retry_times": _bounded_int(
            values["retry_times"],
            "crawler.retry_times",
            0,
            10,
        ),
        "rotate_user_agent": rotate_user_agent,
        "user_agent": user_agent,
        "obey_robots_txt": _strict_bool(
            values["obey_robots_txt"],
            "crawler.obey_robots_txt",
        ),
        "follow_redirects": _strict_bool(
            values["follow_redirects"],
            "crawler.follow_redirects",
        ),
        "max_redirect_times": _bounded_int(
            values["max_redirect_times"],
            "crawler.max_redirect_times",
            0,
            50,
        ),
        "max_depth": _bounded_int(
            values["max_depth"],
            "crawler.max_depth",
            1,
            20,
        ),
        "proxy_enabled": proxy_enabled,
        "proxy_url": proxy_url,
        "log_level": log_level,
    }


def redact_crawler_runtime_config(
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Remove proxy credentials before settings enter logs or audits."""
    redacted = copy.deepcopy(data)
    if redacted.get("proxy_url"):
        redacted["proxy_url"] = "[configured]"
    return redacted


def _bounded_int(
    value: Any,
    field: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是整数")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field} 必须是整数")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是整数") from exc
    if normalized < minimum or normalized > maximum:
        raise ValueError(f"{field} 仅支持 {minimum}-{maximum}")
    return normalized


def _bounded_float(
    value: Any,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是数字")
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是数字") from exc
    if not math.isfinite(normalized):
        raise ValueError(f"{field} 必须是有限数字")
    if normalized < minimum or normalized > maximum:
        raise ValueError(f"{field} 仅支持 {minimum}-{maximum}")
    return normalized


def _strict_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} 必须是布尔值")
    return value
