"""Runtime configuration helpers shared by the Scrapy consumer and worker."""

from __future__ import annotations

import json
from typing import Any, Dict


def build_scrapy_setting_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Map the backend crawler contract to concrete Scrapy setting names."""
    if not config:
        return {}
    return {
        "CONCURRENT_REQUESTS": config["concurrent_requests"],
        "CONCURRENT_REQUESTS_PER_DOMAIN": config[
            "concurrent_requests_per_domain"
        ],
        "DOWNLOAD_DELAY": config["download_delay_seconds"],
        "DOWNLOAD_TIMEOUT": config["request_timeout_seconds"],
        "RETRY_TIMES": config["retry_times"],
        "ROTATE_USER_AGENT_ENABLED": config["rotate_user_agent"],
        "USER_AGENT": config["user_agent"],
        "ROBOTSTXT_OBEY": config["obey_robots_txt"],
        "REDIRECT_ENABLED": config["follow_redirects"],
        "REDIRECT_MAX_TIMES": config["max_redirect_times"],
        "DEPTH_LIMIT": config["max_depth"],
        "HTTPPROXY_ENABLED": config["proxy_enabled"],
        "GLOBAL_PROXY_URL": (
            config["proxy_url"] if config["proxy_enabled"] else ""
        ),
        "LOG_LEVEL": config["log_level"],
    }


def parse_runtime_config(raw: str | None) -> Dict[str, Any]:
    """Decode the JSON snapshot passed from the Redis consumer."""
    if not raw:
        return {}
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("runtime config must be a JSON object")
    return decoded
