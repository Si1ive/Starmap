"""FastAPI dependencies for learning-user sessions and CSRF protection."""

from __future__ import annotations

import hmac
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_db
from app.middleware.error_handler import APIException
from app.modules.identity.context import auth_request_context
from app.modules.identity.models import User
from app.modules.identity.security import csrf_token_digest
from app.modules.identity.session import AuthenticatedSession, SessionService

AUTH_NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
}


def get_session_service(
    db: AsyncSession = Depends(get_db),
) -> SessionService:
    """Build the request-scoped session service."""

    return SessionService(db)


async def require_current_session(
    request: Request,
    service: SessionService = Depends(get_session_service),
) -> AuthenticatedSession:
    """Require a valid learning-user session Cookie."""

    return await _authenticate_or_raise(request, service)


async def require_csrf_session(
    request: Request,
    service: SessionService = Depends(get_session_service),
) -> AuthenticatedSession:
    """Require JSON, a trusted Origin, and the synchronizer CSRF token."""

    validate_json_origin(request)
    current = await _authenticate_or_raise(request, service)
    presented = request.headers.get("x-csrf-token")
    presented_digest = _csrf_digest(presented)
    if presented_digest is None or not hmac.compare_digest(
        presented_digest,
        current.session.csrf_secret_hash,
    ):
        raise APIException(
            message="请求安全校验失败",
            status_code=status.HTTP_403_FORBIDDEN,
            code="CSRF_INVALID",
            headers=AUTH_NO_STORE_HEADERS,
        )
    return current


async def _authenticate_or_raise(
    request: Request,
    service: SessionService,
) -> AuthenticatedSession:
    raw_token = request.cookies.get(settings.AUTH_SESSION_COOKIE_NAME)
    current = await service.authenticate(
        raw_token,
        auth_request_context(request),
    )
    if current is None:
        raise APIException(
            message="请先登录",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            headers={
                **AUTH_NO_STORE_HEADERS,
                "WWW-Authenticate": "Session",
            },
        )
    return current


async def require_current_user(
    current: AuthenticatedSession = Depends(require_current_session),
) -> User:
    """Expose the authenticated learning user to private business routes."""

    return current.user


def validate_json_origin(request: Request) -> None:
    """Reject state-changing browser requests outside the trusted site list."""

    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise APIException(
            message="认证写接口只接受 JSON 请求",
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            code="AUTH_JSON_REQUIRED",
            headers=AUTH_NO_STORE_HEADERS,
        )

    presented_origin = _request_origin(request)
    trusted_origins = {
        normalized
        for value in settings.ALLOWED_ORIGINS
        if (normalized := _normalize_origin(value)) is not None
    }
    if presented_origin is None or presented_origin not in trusted_origins:
        raise APIException(
            message="请求来源校验失败",
            status_code=status.HTTP_403_FORBIDDEN,
            code="AUTH_ORIGIN_INVALID",
            headers=AUTH_NO_STORE_HEADERS,
        )


def _request_origin(request: Request) -> Optional[str]:
    origin = request.headers.get("origin")
    if origin:
        return _normalize_origin(origin)
    referer = request.headers.get("referer")
    if referer:
        return _normalize_origin(referer)
    return None


def _normalize_origin(value: str) -> Optional[str]:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _csrf_digest(value: Optional[str]) -> Optional[bytes]:
    if not value or len(value) > 256:
        return None
    try:
        return csrf_token_digest(value)
    except UnicodeEncodeError:
        return None
