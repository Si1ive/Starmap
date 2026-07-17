"""Redis-backed auth rate limits with a bounded in-process fallback."""

from __future__ import annotations

import asyncio
import math
import secrets
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from app.core.logging import get_logger
from app.db.redis import redis_client
from app.modules.identity.security import identifier_digest

logger = get_logger(__name__)


_SLIDING_WINDOW_SCRIPT = """
local current = redis.call('TIME')
local now_ms = current[1] * 1000 + math.floor(current[2] / 1000)
local cutoff = now_ms - tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, cutoff)
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[2]) then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry_ms = tonumber(ARGV[1])
  if oldest[2] then
    retry_ms = math.max(1, tonumber(oldest[2]) + tonumber(ARGV[1]) - now_ms)
  end
  return {0, retry_ms}
end
redis.call('ZADD', KEYS[1], now_ms, ARGV[3])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[1]))
return {1, 0}
"""


@dataclass(frozen=True)
class RateLimitBucket:
    """One independently enforced auth limit dimension."""

    dimension: str
    value: str
    limit: int
    window_seconds: int


class RateLimitExceeded(RuntimeError):
    """An authentication rate-limit bucket has been exhausted."""

    def __init__(self, action: str, dimension: str, retry_after: int):
        self.action = action
        self.dimension = dimension
        self.retry_after = retry_after
        super().__init__("authentication rate limit exceeded")


class AuthRateLimiter:
    """Apply independent IP, identifier, and browser transaction limits."""

    def __init__(
        self,
        redis_backend: Any | None = None,
        *,
        clock: Any = time.time,
        max_local_buckets: int = 10_000,
    ) -> None:
        self._redis_backend = redis_backend
        self._clock = clock
        self._max_local_buckets = max_local_buckets
        self._local_windows: dict[str, deque[float]] = {}
        self._local_failures: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def enforce(
        self,
        action: str,
        buckets: Iterable[RateLimitBucket],
    ) -> None:
        """Consume all supplied buckets or raise with Retry-After seconds."""

        for bucket in buckets:
            if bucket.limit <= 0 or bucket.window_seconds <= 0:
                raise ValueError("rate-limit values must be positive")
            key = self._key(action, bucket.dimension, bucket.value)
            result = await self._consume_redis(
                key,
                bucket.limit,
                bucket.window_seconds,
            )
            if result is None:
                result = await self._consume_local(
                    key,
                    bucket.limit,
                    bucket.window_seconds,
                )
            allowed, retry_after = result
            if not allowed:
                raise RateLimitExceeded(
                    action,
                    bucket.dimension,
                    retry_after,
                )

    async def record_login_failure(
        self,
        *,
        identifier: str,
        remote_ip: str,
    ) -> float:
        """Record independent failure signals and return progressive delay."""

        keys = (
            self._key("login-failure", "identifier", identifier),
            self._key("login-failure", "ip", remote_ip),
        )
        counts = []
        for key in keys:
            count = await self._increment_failure_redis(key)
            if count is None:
                count = await self._increment_failure_local(key)
            counts.append(count)
        return progressive_delay_seconds(max(counts))

    async def clear_login_failures(self, *, identifier: str) -> None:
        """Clear the account dimension after a successful login."""

        key = self._key("login-failure", "identifier", identifier)
        client = self._redis_client()
        if client is not None:
            try:
                await client.delete(key)
            except Exception as exc:
                logger.warning(
                    "认证失败计数 Redis 清理失败，继续清理本地计数",
                    error=str(exc),
                )
        async with self._lock:
            self._local_failures.pop(key, None)

    async def _consume_redis(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> Optional[tuple[bool, int]]:
        client = self._redis_client()
        if client is None:
            return None
        try:
            result = await client.eval(
                _SLIDING_WINDOW_SCRIPT,
                1,
                key,
                window_seconds * 1000,
                limit,
                secrets.token_hex(12),
            )
            allowed = bool(int(result[0]))
            retry_after = max(1, math.ceil(int(result[1]) / 1000))
            return allowed, retry_after
        except Exception as exc:
            logger.warning(
                "认证限流 Redis 不可用，切换进程内保护",
                error=str(exc),
            )
            return None

    async def _consume_local(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        now = float(self._clock())
        cutoff = now - window_seconds
        async with self._lock:
            window = self._local_windows.setdefault(key, deque())
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= limit:
                retry_after = max(
                    1,
                    math.ceil(window[0] + window_seconds - now),
                )
                return False, retry_after
            window.append(now)
            self._trim_local_state(now)
            return True, 0

    async def _increment_failure_redis(self, key: str) -> Optional[int]:
        client = self._redis_client()
        if client is None:
            return None
        try:
            async with client.pipeline(transaction=True) as pipeline:
                pipeline.incr(key)
                pipeline.expire(key, 15 * 60)
                result = await pipeline.execute()
            return int(result[0])
        except Exception as exc:
            logger.warning(
                "登录失败计数 Redis 不可用，切换进程内保护",
                error=str(exc),
            )
            return None

    async def _increment_failure_local(self, key: str) -> int:
        now = float(self._clock())
        async with self._lock:
            count, expires_at = self._local_failures.get(
                key,
                (0, now + 15 * 60),
            )
            if expires_at <= now:
                count = 0
                expires_at = now + 15 * 60
            count += 1
            self._local_failures[key] = (count, expires_at)
            self._trim_local_state(now)
            return count

    def _trim_local_state(self, now: float) -> None:
        if (
            len(self._local_windows) + len(self._local_failures)
            <= self._max_local_buckets
        ):
            return

        expired_failures = [
            key
            for key, (_, expires_at) in self._local_failures.items()
            if expires_at <= now
        ]
        for key in expired_failures:
            self._local_failures.pop(key, None)

        while (
            len(self._local_windows) + len(self._local_failures)
            > self._max_local_buckets
            and self._local_windows
        ):
            self._local_windows.pop(next(iter(self._local_windows)))
        while (
            len(self._local_windows) + len(self._local_failures)
            > self._max_local_buckets
            and self._local_failures
        ):
            self._local_failures.pop(next(iter(self._local_failures)))

    def _redis_client(self) -> Any | None:
        if self._redis_backend is None:
            return None
        return getattr(self._redis_backend, "_client", None)

    @staticmethod
    def _key(action: str, dimension: str, value: str) -> str:
        digest = identifier_digest(f"{action}:{dimension}:{value}").hex()
        return f"auth:limit:{action}:{dimension}:{digest}"


def progressive_delay_seconds(failure_count: int) -> float:
    """Return a bounded delay after repeated login failures."""

    if failure_count <= 2:
        return 0.0
    return min(2.0, 0.25 * (2 ** (failure_count - 3)))


auth_rate_limiter = AuthRateLimiter(redis_client)


def get_auth_rate_limiter() -> AuthRateLimiter:
    """Return the process-wide authentication limiter."""

    return auth_rate_limiter
