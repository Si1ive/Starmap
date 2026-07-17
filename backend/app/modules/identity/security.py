"""Security primitives shared by learning-user authentication flows."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import re
import secrets
from dataclasses import dataclass
from typing import Optional

from argon2 import PasswordHasher, Type
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)
from email_validator import EmailNotValidError, validate_email

from app.core.config import settings

MIN_PASSWORD_LENGTH = 15
MAX_PASSWORD_LENGTH = 128
SESSION_TOKEN_BYTES = 32
ACTION_TOKEN_BYTES = 32
VERIFICATION_CODE_DIGITS = 6

DEVELOPMENT_ACTION_TOKEN_SECRET = "development-only-action-token-secret-change-me"
DEVELOPMENT_CSRF_SECRET = "development-only-csrf-secret-change-me"
DEVELOPMENT_IDENTIFIER_SECRET = "development-only-identifier-secret-change-me"

COMMON_PASSWORDS = frozenset(
    {
        "123456789012345",
        "1234567890123456",
        "111111111111111",
        "abcdefghijklmnop",
        "adminadminadmin",
        "iloveyouiloveyou",
        "letmeinletmeinletmein",
        "passwordpassword",
        "qwertyuiopasdfgh",
        "starmapstarmap",
    }
)


class PasswordPolicyError(ValueError):
    """A password does not satisfy the registration policy."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PasswordVerification:
    """Result of an Argon2id password verification."""

    valid: bool
    updated_hash: Optional[str] = None


class PasswordService:
    """Hash and verify learning-user passwords with calibrated Argon2id."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=2,
            memory_cost=19 * 1024,
            parallelism=1,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(SESSION_TOKEN_BYTES))

    def validate_new_password(self, password: str) -> None:
        """Enforce length and common-password checks without mutation."""

        try:
            password.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise PasswordPolicyError(
                "PASSWORD_INVALID_ENCODING",
                "密码包含无法处理的字符",
            ) from exc
        if len(password) < MIN_PASSWORD_LENGTH:
            raise PasswordPolicyError(
                "PASSWORD_TOO_SHORT",
                f"密码至少需要 {MIN_PASSWORD_LENGTH} 个字符",
            )
        if len(password) > MAX_PASSWORD_LENGTH:
            raise PasswordPolicyError(
                "PASSWORD_TOO_LONG",
                f"密码不能超过 {MAX_PASSWORD_LENGTH} 个字符",
            )
        if password.casefold() in COMMON_PASSWORDS:
            raise PasswordPolicyError(
                "PASSWORD_TOO_COMMON",
                "该密码过于常见，请更换一个不易猜测的密码",
            )

    def hash_password(self, password: str) -> str:
        """Validate and hash a new password in PHC Argon2id format."""

        self.validate_new_password(password)
        return self._hasher.hash(password)

    def verify_password(
        self,
        password: str,
        password_hash: Optional[str],
    ) -> PasswordVerification:
        """Verify a password and return a transparent rehash when needed."""

        candidate_hash = password_hash or self._dummy_hash
        if len(password) > MAX_PASSWORD_LENGTH:
            password = ""

        try:
            valid = self._hasher.verify(candidate_hash, password)
        except (
            InvalidHashError,
            VerificationError,
            VerifyMismatchError,
            TypeError,
            UnicodeError,
        ):
            return PasswordVerification(valid=False)

        if password_hash is None:
            return PasswordVerification(valid=False)
        updated_hash = None
        if self._hasher.check_needs_rehash(candidate_hash):
            updated_hash = self._hasher.hash(password)
        return PasswordVerification(valid=bool(valid), updated_hash=updated_hash)


def normalize_email(value: str) -> tuple[str, str]:
    """Return deterministic comparison and display forms of an email."""

    candidate = value.strip()
    try:
        validated = validate_email(candidate, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError("邮箱格式无效") from exc

    normalized = validated.normalized
    local_part, domain = normalized.rsplit("@", 1)
    comparison = f"{local_part.casefold()}@{domain.casefold()}"
    return comparison, normalized


def generate_opaque_token() -> str:
    """Generate a URL-safe token with at least 256 bits of entropy."""

    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def generate_verification_code() -> str:
    """Generate a zero-padded cryptographically secure six-digit code."""

    upper_bound = 10**VERIFICATION_CODE_DIGITS
    return f"{secrets.randbelow(upper_bound):0{VERIFICATION_CODE_DIGITS}d}"


def session_token_digest(token: str) -> bytes:
    """Hash an opaque session token before persistence."""

    return hashlib.sha256(token.encode("utf-8")).digest()


def action_token_digest(
    token: str,
    purpose: str,
    *,
    secret: Optional[str] = None,
) -> bytes:
    """Create a domain-separated HMAC digest for a one-time token."""

    key = (secret or settings.AUTH_ACTION_TOKEN_SECRET).encode("utf-8")
    message = f"starmap:action:{purpose}:{token}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).digest()


def identifier_digest(
    identifier: str,
    *,
    secret: Optional[str] = None,
) -> bytes:
    """Create a non-reversible identifier digest for limits and audit."""

    key = (secret or settings.AUTH_IDENTIFIER_HMAC_SECRET).encode("utf-8")
    message = f"starmap:identifier:{identifier}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).digest()


def derive_csrf_token(
    session_token: str,
    *,
    secret: Optional[str] = None,
) -> str:
    """Derive a stable CSRF token from the opaque browser session."""

    key = (secret or settings.AUTH_CSRF_SECRET).encode("utf-8")
    message = f"starmap:csrf:{session_token}".encode("utf-8")
    digest = hmac.new(key, message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def csrf_token_digest(token: str) -> bytes:
    """Hash the derived CSRF token before persistence."""

    return hashlib.sha256(token.encode("ascii")).digest()


def pack_ip_address(value: Optional[str]) -> Optional[bytes]:
    """Pack an IPv4 or IPv6 address for a VARBINARY(16) column."""

    if not value:
        return None
    try:
        return ipaddress.ip_address(value).packed
    except ValueError:
        return None


def sanitize_user_agent(value: Optional[str]) -> Optional[str]:
    """Remove control characters and bound persisted User-Agent data."""

    if not value:
        return None
    sanitized = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
    return sanitized[:512] or None


def infer_device_label(user_agent: Optional[str]) -> Optional[str]:
    """Build a coarse display label without storing a device fingerprint."""

    if not user_agent:
        return None
    browser = "Browser"
    if "Edg/" in user_agent:
        browser = "Edge"
    elif "Chrome/" in user_agent:
        browser = "Chrome"
    elif "Firefox/" in user_agent:
        browser = "Firefox"
    elif "Safari/" in user_agent:
        browser = "Safari"

    platform = "Unknown device"
    if "Windows" in user_agent:
        platform = "Windows"
    elif "Macintosh" in user_agent:
        platform = "macOS"
    elif "Android" in user_agent:
        platform = "Android"
    elif "iPhone" in user_agent or "iPad" in user_agent:
        platform = "iOS"
    elif "Linux" in user_agent:
        platform = "Linux"
    return f"{browser} on {platform}"


def validate_user_auth_security_config() -> None:
    """Reject unsafe learning-user auth settings outside local environments."""

    if settings.ENV in {"development", "test"}:
        return

    secret_pairs = (
        (
            "AUTH_ACTION_TOKEN_SECRET",
            settings.AUTH_ACTION_TOKEN_SECRET,
            DEVELOPMENT_ACTION_TOKEN_SECRET,
        ),
        (
            "AUTH_CSRF_SECRET",
            settings.AUTH_CSRF_SECRET,
            DEVELOPMENT_CSRF_SECRET,
        ),
        (
            "AUTH_IDENTIFIER_HMAC_SECRET",
            settings.AUTH_IDENTIFIER_HMAC_SECRET,
            DEVELOPMENT_IDENTIFIER_SECRET,
        ),
    )
    for name, value, development_value in secret_pairs:
        if value == development_value or len(value) < 32:
            raise RuntimeError(
                f"{name} must be set to a unique value of at least 32 characters"
            )

    for name, value in (
        ("AUTH_SESSION_COOKIE_NAME", settings.AUTH_SESSION_COOKIE_NAME),
        (
            "AUTH_REGISTRATION_COOKIE_NAME",
            settings.AUTH_REGISTRATION_COOKIE_NAME,
        ),
        (
            "AUTH_GITHUB_OAUTH_COOKIE_NAME",
            settings.AUTH_GITHUB_OAUTH_COOKIE_NAME,
        ),
    ):
        if not value.startswith("__Host-"):
            raise RuntimeError(f"{name} must use the __Host- prefix")

    if not settings.AUTH_COOKIE_SECURE:
        raise RuntimeError("AUTH_COOKIE_SECURE must be enabled in production")
    if settings.AUTH_EMAIL_BACKEND != "memory":
        raise RuntimeError("AUTH_EMAIL_BACKEND is not supported by this build")
    if settings.AUTH_ANTI_BOT_MODE != "disabled":
        raise RuntimeError("AUTH_ANTI_BOT_MODE is not supported by this build")
    if settings.AUTH_EMAIL_BACKEND == "memory":
        raise RuntimeError("AUTH_EMAIL_BACKEND must be configured in production")
    if settings.AUTH_ANTI_BOT_MODE == "disabled":
        raise RuntimeError("AUTH_ANTI_BOT_MODE must be configured in production")
    if "*" in settings.ALLOWED_ORIGINS:
        raise RuntimeError("ALLOWED_ORIGINS cannot contain a wildcard")
    if any(not origin.startswith("https://") for origin in settings.ALLOWED_ORIGINS):
        raise RuntimeError("ALLOWED_ORIGINS must use HTTPS in production")
    if not settings.AUTH_FRONTEND_BASE_URL.startswith("https://"):
        raise RuntimeError("AUTH_FRONTEND_BASE_URL must use HTTPS in production")
    github_values = (
        settings.AUTH_GITHUB_CLIENT_ID,
        settings.AUTH_GITHUB_CLIENT_SECRET,
    )
    if any(github_values) and not all(github_values):
        raise RuntimeError(
            "AUTH_GITHUB_CLIENT_ID and AUTH_GITHUB_CLIENT_SECRET "
            "must be configured together"
        )
    if all(github_values) and not settings.AUTH_GITHUB_CALLBACK_URL.startswith(
        "https://"
    ):
        raise RuntimeError("AUTH_GITHUB_CALLBACK_URL must use HTTPS in production")


_password_service: Optional[PasswordService] = None


def get_password_service() -> PasswordService:
    """Return the process-wide Argon2id password service."""

    global _password_service
    if _password_service is None:
        _password_service = PasswordService()
    return _password_service
