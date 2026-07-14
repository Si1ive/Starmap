"""Authentication primitives for the administration API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import NoReturn

import bcrypt
from fastapi import Depends, HTTPException, WebSocketException, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.core.config import settings
from app.db import get_db
from app.models.mysql_models import AdminUser


PBKDF2_SCHEME = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 260_000
ACCESS_TOKEN_TYPE = "admin_access"
DEVELOPMENT_JWT_SECRET = "development-only-admin-jwt-secret-change-me"


def hash_admin_password(password: str) -> str:
    """Hash an administrator password with the project's portable format."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return "{}${}${}${}".format(
        PBKDF2_SCHEME,
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_admin_password(password: str, password_hash: str) -> bool:
    """Verify current PBKDF2 hashes and legacy bcrypt hashes."""
    if not isinstance(password_hash, str):
        return False
    if password_hash.startswith(f"{PBKDF2_SCHEME}$"):
        try:
            scheme, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
            iterations = int(iterations_text)
            if scheme != PBKDF2_SCHEME or iterations <= 0 or iterations > 2_000_000:
                return False
            salt = base64.b64decode(salt_text, validate=True)
            expected = base64.b64decode(digest_text, validate=True)
        except (ValueError, TypeError):
            return False

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(actual, expected)

    if password_hash.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"),
                password_hash.encode("ascii"),
            )
        except (ValueError, TypeError, UnicodeError):
            return False

    return False


def needs_password_rehash(password_hash: str) -> bool:
    """Return whether a valid legacy or weaker hash should be upgraded."""
    if not isinstance(password_hash, str):
        return True
    if not password_hash.startswith(f"{PBKDF2_SCHEME}$"):
        return True
    try:
        return int(password_hash.split("$", 3)[1]) < PBKDF2_ITERATIONS
    except (ValueError, IndexError):
        return True


def create_admin_access_token(user_id: str) -> str:
    """Create a short-lived signed token for an administrator."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ADMIN_JWT_EXPIRE_MINUTES),
        "iss": settings.ADMIN_JWT_ISSUER,
        "aud": settings.ADMIN_JWT_AUDIENCE,
    }
    return jwt.encode(
        payload,
        settings.ADMIN_JWT_SECRET,
        algorithm=settings.ADMIN_JWT_ALGORITHM,
    )


def decode_admin_access_token(token: str) -> str:
    """Validate an access token and return its administrator ID."""
    try:
        payload = jwt.decode(
            token,
            settings.ADMIN_JWT_SECRET,
            algorithms=[settings.ADMIN_JWT_ALGORITHM],
            issuer=settings.ADMIN_JWT_ISSUER,
            audience=settings.ADMIN_JWT_AUDIENCE,
        )
    except JWTError as exc:
        raise ValueError("invalid admin access token") from exc

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise ValueError("invalid admin access token type")
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("admin access token has no subject")
    return user_id


def validate_admin_security_config() -> None:
    """Reject unsafe JWT configuration outside local and test environments."""
    if settings.ENV in {"development", "test"}:
        return
    if (
        settings.ADMIN_JWT_SECRET == DEVELOPMENT_JWT_SECRET
        or len(settings.ADMIN_JWT_SECRET) < 32
    ):
        raise RuntimeError(
            "ADMIN_JWT_SECRET must be set to a unique value of at least 32 characters"
        )


def get_admin_access_token(connection: HTTPConnection) -> str:
    """Extract a bearer token from HTTP headers or a WebSocket query."""
    auth_header = connection.headers.get("Authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token

    if connection.scope["type"] == "websocket":
        query_token = connection.query_params.get("token")
        if query_token:
            return query_token

    _raise_authentication_error(connection)


async def require_current_admin(
    connection: HTTPConnection,
    token: str = Depends(get_admin_access_token),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    """Resolve the active database administrator for the current request."""
    try:
        user_id = decode_admin_access_token(token)
    except ValueError:
        _raise_authentication_error(connection)

    user = await db.get(AdminUser, user_id)
    if user is None or not user.is_active:
        _raise_authentication_error(connection)

    connection.state.admin_user = user
    connection.state.admin_user_id = user.id
    return user


async def require_user_manager(
    current_admin: AdminUser = Depends(require_current_admin),
) -> AdminUser:
    """Require the explicit user-management permission or super-admin role."""
    permissions = current_admin.permissions or []
    if (
        current_admin.role == "super_admin"
        or "*" in permissions
        or "user:manage" in permissions
    ):
        return current_admin
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有用户管理权限")


def get_request_admin_id(connection: HTTPConnection) -> str | None:
    """Return the administrator ID populated by the authentication dependency."""
    return getattr(connection.state, "admin_user_id", None)


def _raise_authentication_error(connection: HTTPConnection) -> NoReturn:
    if connection.scope["type"] == "websocket":
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已过期或凭证无效",
        headers={"WWW-Authenticate": "Bearer"},
    )
