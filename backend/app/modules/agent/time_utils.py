"""Agent API 的 UTC 时间边界工具。

MySQL 的 DATETIME 不携带时区。项目约定其中的 Agent 时间均表示 UTC，
因此在发给浏览器前必须补上明确的 UTC 标记。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    """返回用于 MySQL DATETIME 的 naive UTC 当前时间。

    数据库列保持既有无时区结构；只有进入 API 边界时才补 UTC 标记。
    """
    return datetime.now(UTC).replace(tzinfo=None)


def as_utc(value: datetime | None) -> datetime | None:
    """把数据库返回的 naive UTC 时间转换为带时区的 UTC 时间。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_isoformat(value: datetime | None) -> str | None:
    """输出浏览器可无歧义解析的 ISO 8601 UTC 字符串。"""
    normalized = as_utc(value)
    if normalized is None:
        return None
    return normalized.isoformat().replace("+00:00", "Z")


def encode_utc_datetimes(value: Any) -> Any:
    """递归转换响应/SSE 数据中的 datetime，保留其他值不变。"""
    if isinstance(value, datetime):
        return utc_isoformat(value)
    if isinstance(value, dict):
        return {key: encode_utc_datetimes(item) for key, item in value.items()}
    if isinstance(value, list):
        return [encode_utc_datetimes(item) for item in value]
    if isinstance(value, tuple):
        return [encode_utc_datetimes(item) for item in value]
    return value
