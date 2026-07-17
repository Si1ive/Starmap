"""Anti-automation verification boundary for anonymous auth writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from app.core.config import settings


@dataclass(frozen=True)
class AntiBotDecision:
    """Normalized result returned by any anti-automation provider."""

    allowed: bool
    reason: str = "allowed"


class AntiBotUnavailable(RuntimeError):
    """The configured anti-automation provider cannot verify a request."""


class AntiBotVerifier(Protocol):
    """Verify a short-lived provider token on the server."""

    async def verify(
        self,
        token: Optional[str],
        *,
        action: str,
        remote_ip: Optional[str],
    ) -> AntiBotDecision:
        """Return a normalized allow or deny decision."""


class DevelopmentAntiBotVerifier:
    """Allow local requests while preserving the production interface."""

    async def verify(
        self,
        token: Optional[str],
        *,
        action: str,
        remote_ip: Optional[str],
    ) -> AntiBotDecision:
        return AntiBotDecision(allowed=True, reason="development_bypass")


class UnavailableAntiBotVerifier:
    """Fail closed until a deployment-specific provider is configured."""

    async def verify(
        self,
        token: Optional[str],
        *,
        action: str,
        remote_ip: Optional[str],
    ) -> AntiBotDecision:
        raise AntiBotUnavailable("anti-automation verification is not configured")


development_anti_bot_verifier = DevelopmentAntiBotVerifier()
unavailable_anti_bot_verifier = UnavailableAntiBotVerifier()


def get_anti_bot_verifier() -> AntiBotVerifier:
    """Resolve the configured verifier for dependency injection."""

    if settings.AUTH_ANTI_BOT_MODE == "disabled" and settings.ENV in {
        "development",
        "test",
    }:
        return development_anti_bot_verifier
    return unavailable_anti_bot_verifier
