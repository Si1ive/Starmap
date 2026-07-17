"""Request metadata shared by learning-user authentication flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from app.core.logging import get_request_id


@dataclass(frozen=True)
class AuthRequestContext:
    """Bounded request metadata persisted for authentication auditing."""

    remote_ip: Optional[str]
    user_agent: Optional[str]
    request_id: Optional[str]


def auth_request_context(request: Request) -> AuthRequestContext:
    """Build authentication metadata without retaining the request object."""

    return AuthRequestContext(
        remote_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=get_request_id(),
    )
