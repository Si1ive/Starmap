"""Replaceable email-delivery boundary for authentication messages."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Mapping, Protocol

from app.core.config import settings


@dataclass(frozen=True)
class AuthEmail:
    """Authentication email queued after the database transaction commits."""

    template_id: str
    recipient: str
    variables: Mapping[str, str]
    idempotency_key: str


class EmailDeliveryUnavailable(RuntimeError):
    """No production email queue or provider is currently available."""


class EmailSender(Protocol):
    """Queue an authentication email without exposing provider details."""

    async def enqueue(self, message: AuthEmail) -> None:
        """Queue one idempotent message for asynchronous delivery."""


class MemoryEmailSender:
    """Bounded development outbox that never writes token values to logs."""

    def __init__(self, capacity: int = 100) -> None:
        self._messages: deque[AuthEmail] = deque(maxlen=capacity)
        self._lock = asyncio.Lock()

    async def enqueue(self, message: AuthEmail) -> None:
        async with self._lock:
            self._messages.append(message)

    async def latest_for(self, recipient: str) -> AuthEmail | None:
        """Return the latest local message for integration tests and tooling."""

        async with self._lock:
            for message in reversed(self._messages):
                if message.recipient == recipient:
                    return message
        return None

    async def clear(self) -> None:
        async with self._lock:
            self._messages.clear()


class UnavailableEmailSender:
    """Fail closed when no non-development email adapter is configured."""

    async def enqueue(self, message: AuthEmail) -> None:
        raise EmailDeliveryUnavailable(
            "authentication email delivery is not configured"
        )


memory_email_sender = MemoryEmailSender()
unavailable_email_sender = UnavailableEmailSender()


def get_email_sender() -> EmailSender:
    """Resolve the configured email adapter for FastAPI dependency injection."""

    if settings.AUTH_EMAIL_BACKEND == "memory" and settings.ENV in {
        "development",
        "test",
    }:
        return memory_email_sender
    return unavailable_email_sender
