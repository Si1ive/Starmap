"""Password login and revocable server-side learning-user sessions."""

from __future__ import annotations

import asyncio
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from ipaddress import ip_address
from typing import Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.types import new_uuid7
from app.modules.identity.context import AuthRequestContext
from app.modules.identity.models import (
    AuthEvent,
    AuthSession,
    PasswordCredential,
    User,
    UserProfile,
    utc_now,
)
from app.modules.identity.rate_limit import AuthRateLimiter
from app.modules.identity.schemas import LoginRequest
from app.modules.identity.security import (
    PasswordService,
    csrf_token_digest,
    derive_csrf_token,
    generate_opaque_token,
    identifier_digest,
    infer_device_label,
    normalize_email,
    pack_ip_address,
    sanitize_user_agent,
    session_token_digest,
)


class LoginFlowError(ValueError):
    """A user-safe password-login failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
    ) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class SessionManagementError(ValueError):
    """A user-safe failure while managing authenticated sessions."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
    ) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class LoginOutcome:
    """Successful login data plus the plaintext browser credentials."""

    user: User
    profile: Optional[UserProfile]
    session: AuthSession
    session_token: str
    csrf_token: str
    cookie_max_age: Optional[int]


@dataclass(frozen=True)
class AuthenticatedSession:
    """Validated current user and session for one request."""

    user: User
    profile: Optional[UserProfile]
    session: AuthSession
    csrf_token: str


@dataclass(frozen=True)
class SessionSummary:
    """Redacted session metadata safe for account settings."""

    id: uuid.UUID
    auth_method: str
    device_label: str
    created_at: datetime
    last_seen_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    is_current: bool
    location_label: Optional[str]


class LoginService:
    """Verify email credentials and create a rotated opaque session."""

    def __init__(
        self,
        db: AsyncSession,
        password_service: PasswordService,
        rate_limiter: AuthRateLimiter,
        *,
        clock: Callable[[], datetime] = utc_now,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.db = db
        self.password_service = password_service
        self.rate_limiter = rate_limiter
        self.clock = clock
        self.sleeper = sleeper

    async def login(
        self,
        payload: LoginRequest,
        context: AuthRequestContext,
        previous_session_token: Optional[str],
    ) -> LoginOutcome:
        """Authenticate a password without exposing account existence."""

        normalized_email = self._normalize_login_email(payload.email)
        identifier = normalized_email or self._fallback_identifier(payload.email)
        user = None
        credential = None
        if normalized_email:
            user = await self.db.scalar(
                select(User).where(User.email_normalized == normalized_email)
            )
            if user is not None:
                credential = await self.db.get(PasswordCredential, user.id)

        initial_hash = credential.password_hash if credential else None
        verification = self.password_service.verify_password(
            payload.password,
            initial_hash,
        )
        if not verification.valid or user is None or credential is None:
            await self._deny_invalid_credentials(
                user_id=user.id if user else None,
                identifier=identifier,
                context=context,
            )

        locked_user = await self.db.scalar(
            select(User)
            .where(User.id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        locked_credential = await self.db.scalar(
            select(PasswordCredential)
            .where(PasswordCredential.user_id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_user is None or locked_credential is None:
            await self._deny_invalid_credentials(
                user_id=user.id,
                identifier=identifier,
                context=context,
            )

        if locked_credential.password_hash != initial_hash:
            verification = self.password_service.verify_password(
                payload.password,
                locked_credential.password_hash,
            )
            if not verification.valid:
                await self._deny_invalid_credentials(
                    user_id=locked_user.id,
                    identifier=identifier,
                    context=context,
                )

        if (
            locked_user.status == "pending_email"
            or locked_user.email_verified_at is None
        ):
            await self._deny_account_state(
                locked_user,
                identifier,
                context,
                reason_code="email_verification_required",
                code="EMAIL_VERIFICATION_REQUIRED",
                message="请先完成邮箱验证",
            )
        if (
            locked_user.status != "active"
            or locked_user.deleted_at is not None
            or locked_user.suspended_at is not None
            or locked_credential.must_change
            or locked_credential.compromised_at is not None
        ):
            await self._deny_account_state(
                locked_user,
                identifier,
                context,
                reason_code="account_login_unavailable",
                code="ACCOUNT_LOGIN_UNAVAILABLE",
                message="账号当前无法登录，请联系支持",
            )

        now = self.clock()
        if verification.updated_hash:
            locked_credential.password_hash = verification.updated_hash
            locked_credential.updated_at = now

        await self._revoke_presented_session(previous_session_token, now)
        session_token = generate_opaque_token()
        csrf_token = derive_csrf_token(session_token)
        idle_lifetime, absolute_lifetime = self._session_lifetimes(payload.remember_me)
        auth_session = AuthSession(
            id=new_uuid7(),
            user_id=locked_user.id,
            token_hash=session_token_digest(session_token),
            csrf_secret_hash=csrf_token_digest(csrf_token),
            auth_version=locked_user.auth_version,
            auth_method="password",
            created_ip=pack_ip_address(context.remote_ip),
            last_ip=pack_ip_address(context.remote_ip),
            user_agent=sanitize_user_agent(context.user_agent),
            device_label=infer_device_label(context.user_agent),
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + idle_lifetime,
            absolute_expires_at=now + absolute_lifetime,
        )
        self.db.add(auth_session)
        await self.db.flush()
        locked_user.last_login_at = now
        locked_user.last_login_method = "password"
        locked_user.updated_at = now
        locked_user.row_version += 1
        self._record_event(
            event_type="login",
            outcome="success",
            user_id=locked_user.id,
            session_id=auth_session.id,
            identifier=identifier,
            context=context,
        )
        profile = await self.db.get(UserProfile, locked_user.id)
        await self.db.commit()
        await self.rate_limiter.clear_login_failures(identifier=identifier)

        cookie_max_age = None
        if payload.remember_me:
            cookie_max_age = int(absolute_lifetime.total_seconds())
        return LoginOutcome(
            user=locked_user,
            profile=profile,
            session=auth_session,
            session_token=session_token,
            csrf_token=csrf_token,
            cookie_max_age=cookie_max_age,
        )

    async def _deny_invalid_credentials(
        self,
        *,
        user_id: Optional[uuid.UUID],
        identifier: str,
        context: AuthRequestContext,
    ) -> None:
        self._record_event(
            event_type="login",
            outcome="failure",
            user_id=user_id,
            session_id=None,
            identifier=identifier,
            context=context,
            reason_code="invalid_credentials",
        )
        await self.db.commit()
        delay = await self.rate_limiter.record_login_failure(
            identifier=identifier,
            remote_ip=context.remote_ip or "unknown",
        )
        if delay > 0:
            await self.sleeper(delay)
        raise LoginFlowError(
            "AUTH_INVALID_CREDENTIALS",
            "邮箱或密码错误",
            status_code=401,
        )

    async def _deny_account_state(
        self,
        user: User,
        identifier: str,
        context: AuthRequestContext,
        *,
        reason_code: str,
        code: str,
        message: str,
    ) -> None:
        self._record_event(
            event_type="login",
            outcome="denied",
            user_id=user.id,
            session_id=None,
            identifier=identifier,
            context=context,
            reason_code=reason_code,
        )
        await self.db.commit()
        await self.rate_limiter.clear_login_failures(identifier=identifier)
        raise LoginFlowError(code, message, status_code=403)

    async def _revoke_presented_session(
        self,
        raw_token: Optional[str],
        now: datetime,
    ) -> None:
        if not _is_bounded_token(raw_token):
            return
        existing = await self.db.scalar(
            select(AuthSession)
            .where(AuthSession.token_hash == session_token_digest(raw_token))
            .with_for_update()
        )
        if existing is not None and existing.revoked_at is None:
            existing.revoked_at = now
            existing.revoke_reason = "login_rotation"

    def _record_event(
        self,
        *,
        event_type: str,
        outcome: str,
        user_id: Optional[uuid.UUID],
        session_id: Optional[uuid.UUID],
        identifier: str,
        context: AuthRequestContext,
        reason_code: Optional[str] = None,
    ) -> None:
        self.db.add(
            AuthEvent(
                user_id=user_id,
                session_id=session_id,
                event_type=event_type,
                outcome=outcome,
                provider="password",
                reason_code=reason_code,
                identifier_hmac=identifier_digest(identifier),
                ip_address=pack_ip_address(context.remote_ip),
                user_agent=sanitize_user_agent(context.user_agent),
                request_id=(context.request_id or "")[:64] or None,
            )
        )

    @staticmethod
    def _normalize_login_email(value: str) -> Optional[str]:
        try:
            normalized, _ = normalize_email(value)
        except ValueError:
            return None
        return normalized

    @staticmethod
    def _fallback_identifier(value: str) -> str:
        return value.strip().casefold()[:320] or "invalid-email"

    @staticmethod
    def _session_lifetimes(remember_me: bool) -> tuple[timedelta, timedelta]:
        if remember_me:
            return (
                timedelta(days=settings.AUTH_REMEMBER_IDLE_DAYS),
                timedelta(days=settings.AUTH_REMEMBER_ABSOLUTE_DAYS),
            )
        return (
            timedelta(hours=settings.AUTH_SESSION_IDLE_HOURS),
            timedelta(days=settings.AUTH_SESSION_ABSOLUTE_DAYS),
        )


class SessionService:
    """Resolve, touch, and revoke opaque browser sessions."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.clock = clock

    async def create_after_email_verification(
        self,
        user_id: uuid.UUID,
        context: AuthRequestContext,
        previous_session_token: Optional[str],
    ) -> Optional[LoginOutcome]:
        """Create a short-lived browser session for a just-verified user."""

        user = await self.db.scalar(
            select(User)
            .options(selectinload(User.profile))
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            user is None
            or user.status != "active"
            or user.email_verified_at is None
            or user.deleted_at is not None
            or user.suspended_at is not None
        ):
            await self.db.rollback()
            return None

        now = self.clock()
        await self._revoke_presented_session(
            previous_session_token,
            now,
            reason="email_verification_rotation",
        )
        session_token = generate_opaque_token()
        csrf_token = derive_csrf_token(session_token)
        idle_lifetime = timedelta(hours=settings.AUTH_SESSION_IDLE_HOURS)
        absolute_lifetime = timedelta(days=settings.AUTH_SESSION_ABSOLUTE_DAYS)
        auth_session = AuthSession(
            id=new_uuid7(),
            user_id=user.id,
            token_hash=session_token_digest(session_token),
            csrf_secret_hash=csrf_token_digest(csrf_token),
            auth_version=user.auth_version,
            auth_method="email_verification",
            created_ip=pack_ip_address(context.remote_ip),
            last_ip=pack_ip_address(context.remote_ip),
            user_agent=sanitize_user_agent(context.user_agent),
            device_label=infer_device_label(context.user_agent),
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + idle_lifetime,
            absolute_expires_at=now + absolute_lifetime,
        )
        self.db.add(auth_session)
        await self.db.flush()
        user.last_login_at = now
        user.last_login_method = "email_verification"
        user.updated_at = now
        user.row_version += 1
        self.db.add(
            AuthEvent(
                user_id=user.id,
                session_id=auth_session.id,
                event_type="login",
                outcome="success",
                provider="email_verification",
                reason_code="same_browser_verification",
                identifier_hmac=identifier_digest(
                    user.email_normalized or str(user.id)
                ),
                ip_address=pack_ip_address(context.remote_ip),
                user_agent=sanitize_user_agent(context.user_agent),
                request_id=(context.request_id or "")[:64] or None,
            )
        )
        await self.db.commit()
        return LoginOutcome(
            user=user,
            profile=user.profile,
            session=auth_session,
            session_token=session_token,
            csrf_token=csrf_token,
            cookie_max_age=None,
        )

    async def create_for_external_login(
        self,
        user_id: uuid.UUID,
        *,
        auth_method: str,
        context: AuthRequestContext,
        previous_session_token: Optional[str],
        remember_me: bool,
    ) -> Optional[LoginOutcome]:
        """Create and rotate a session after a trusted external login."""

        if not auth_method or len(auth_method) > 32:
            raise ValueError("invalid external authentication method")
        user = await self.db.scalar(
            select(User)
            .options(selectinload(User.profile))
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            user is None
            or user.status != "active"
            or user.email_verified_at is None
            or user.deleted_at is not None
            or user.suspended_at is not None
        ):
            await self.db.rollback()
            return None

        now = self.clock()
        await self._revoke_presented_session(
            previous_session_token,
            now,
            reason=f"{auth_method}_login_rotation",
        )
        session_token = generate_opaque_token()
        csrf_token = derive_csrf_token(session_token)
        if remember_me:
            idle_lifetime = timedelta(days=settings.AUTH_REMEMBER_IDLE_DAYS)
            absolute_lifetime = timedelta(days=settings.AUTH_REMEMBER_ABSOLUTE_DAYS)
        else:
            idle_lifetime = timedelta(hours=settings.AUTH_SESSION_IDLE_HOURS)
            absolute_lifetime = timedelta(days=settings.AUTH_SESSION_ABSOLUTE_DAYS)
        auth_session = AuthSession(
            id=new_uuid7(),
            user_id=user.id,
            token_hash=session_token_digest(session_token),
            csrf_secret_hash=csrf_token_digest(csrf_token),
            auth_version=user.auth_version,
            auth_method=auth_method,
            created_ip=pack_ip_address(context.remote_ip),
            last_ip=pack_ip_address(context.remote_ip),
            user_agent=sanitize_user_agent(context.user_agent),
            device_label=infer_device_label(context.user_agent),
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + idle_lifetime,
            absolute_expires_at=now + absolute_lifetime,
        )
        self.db.add(auth_session)
        await self.db.flush()
        user.last_login_at = now
        user.last_login_method = auth_method
        user.updated_at = now
        user.row_version += 1
        self.db.add(
            AuthEvent(
                user_id=user.id,
                session_id=auth_session.id,
                event_type="login",
                outcome="success",
                provider=auth_method,
                reason_code="external_oauth_callback",
                identifier_hmac=identifier_digest(
                    user.email_normalized or str(user.id)
                ),
                ip_address=pack_ip_address(context.remote_ip),
                user_agent=sanitize_user_agent(context.user_agent),
                request_id=(context.request_id or "")[:64] or None,
            )
        )
        await self.db.commit()
        return LoginOutcome(
            user=user,
            profile=user.profile,
            session=auth_session,
            session_token=session_token,
            csrf_token=csrf_token,
            cookie_max_age=(
                int(absolute_lifetime.total_seconds()) if remember_me else None
            ),
        )

    async def authenticate(
        self,
        raw_token: Optional[str],
        context: AuthRequestContext,
    ) -> Optional[AuthenticatedSession]:
        """Return a current session only when every server-side check passes."""

        if not _is_bounded_token(raw_token):
            return None
        token_hash = session_token_digest(raw_token)
        auth_session = await self.db.scalar(
            select(AuthSession)
            .options(
                selectinload(AuthSession.user).selectinload(User.profile),
            )
            .where(AuthSession.token_hash == token_hash)
        )
        if auth_session is None or auth_session.revoked_at is not None:
            return None

        now = self.clock()
        user = auth_session.user
        revoke_reason = self._invalid_reason(auth_session, user, now)
        csrf_token = derive_csrf_token(raw_token)
        if revoke_reason is None and not hmac.compare_digest(
            csrf_token_digest(csrf_token),
            auth_session.csrf_secret_hash,
        ):
            revoke_reason = "csrf_secret_mismatch"
        if revoke_reason is not None:
            await self._revoke_invalid_session(
                auth_session,
                context,
                now,
                revoke_reason,
            )
            return None

        if now - auth_session.last_seen_at >= timedelta(
            minutes=settings.AUTH_SESSION_TOUCH_MINUTES
        ):
            idle_lifetime = self._idle_lifetime(auth_session)
            auth_session.last_seen_at = now
            auth_session.last_ip = pack_ip_address(context.remote_ip)
            auth_session.idle_expires_at = min(
                now + idle_lifetime,
                auth_session.absolute_expires_at,
            )
            await self.db.commit()

        return AuthenticatedSession(
            user=user,
            profile=user.profile,
            session=auth_session,
            csrf_token=csrf_token,
        )

    async def logout(
        self,
        current: AuthenticatedSession,
        context: AuthRequestContext,
    ) -> None:
        """Revoke the current session and append a logout audit event."""

        auth_session = await self.db.scalar(
            select(AuthSession)
            .where(AuthSession.id == current.session.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if auth_session is None or auth_session.revoked_at is not None:
            await self.db.rollback()
            return
        now = self.clock()
        auth_session.revoked_at = now
        auth_session.revoke_reason = "logout"
        self.db.add(
            AuthEvent(
                user_id=auth_session.user_id,
                session_id=auth_session.id,
                event_type="logout",
                outcome="success",
                ip_address=pack_ip_address(context.remote_ip),
                user_agent=sanitize_user_agent(context.user_agent),
                request_id=(context.request_id or "")[:64] or None,
            )
        )
        await self.db.commit()

    async def list_active_sessions(
        self,
        current: AuthenticatedSession,
    ) -> list[SessionSummary]:
        """Return only effective sessions owned by the current user."""

        now = self.clock()
        sessions = (
            await self.db.scalars(
                select(AuthSession)
                .where(
                    AuthSession.user_id == current.user.id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.auth_version == current.user.auth_version,
                    AuthSession.idle_expires_at > now,
                    AuthSession.absolute_expires_at > now,
                )
                .order_by(
                    AuthSession.last_seen_at.desc(),
                    AuthSession.created_at.desc(),
                )
            )
        ).all()
        summaries = [
            self._session_summary(
                auth_session,
                is_current=auth_session.id == current.session.id,
            )
            for auth_session in sessions
        ]
        return sorted(summaries, key=lambda item: not item.is_current)

    async def revoke_other_session(
        self,
        current: AuthenticatedSession,
        session_id: uuid.UUID,
        context: AuthRequestContext,
    ) -> None:
        """Revoke one active session after enforcing object ownership."""

        if session_id == current.session.id:
            raise SessionManagementError(
                "CURRENT_SESSION_LOGOUT_REQUIRED",
                "当前会话请使用退出登录",
                status_code=409,
            )

        auth_session = await self.db.scalar(
            select(AuthSession)
            .where(
                AuthSession.id == session_id,
                AuthSession.user_id == current.user.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = self.clock()
        if (
            auth_session is None
            or auth_session.revoked_at is not None
            or self._invalid_reason(auth_session, current.user, now) is not None
        ):
            raise SessionManagementError(
                "SESSION_NOT_FOUND",
                "登录会话不存在或已失效",
                status_code=404,
            )

        auth_session.revoked_at = now
        auth_session.revoke_reason = "user_revoked_other_session"
        self.db.add(
            AuthEvent(
                user_id=current.user.id,
                session_id=auth_session.id,
                event_type="session_revoked",
                outcome="success",
                provider=auth_session.auth_method,
                reason_code="user_revoked_other_session",
                ip_address=pack_ip_address(context.remote_ip),
                user_agent=sanitize_user_agent(context.user_agent),
                request_id=(context.request_id or "")[:64] or None,
            )
        )
        await self.db.commit()

    async def _revoke_presented_session(
        self,
        raw_token: Optional[str],
        now: datetime,
        *,
        reason: str,
    ) -> None:
        if not _is_bounded_token(raw_token):
            return
        existing = await self.db.scalar(
            select(AuthSession)
            .where(AuthSession.token_hash == session_token_digest(raw_token))
            .with_for_update()
        )
        if existing is not None and existing.revoked_at is None:
            existing.revoked_at = now
            existing.revoke_reason = reason

    async def _revoke_invalid_session(
        self,
        auth_session: AuthSession,
        context: AuthRequestContext,
        now: datetime,
        reason: str,
    ) -> None:
        auth_session.revoked_at = now
        auth_session.revoke_reason = reason
        self.db.add(
            AuthEvent(
                user_id=auth_session.user_id,
                session_id=auth_session.id,
                event_type="session_rejected",
                outcome="denied",
                reason_code=reason,
                ip_address=pack_ip_address(context.remote_ip),
                user_agent=sanitize_user_agent(context.user_agent),
                request_id=(context.request_id or "")[:64] or None,
            )
        )
        await self.db.commit()

    @staticmethod
    def _invalid_reason(
        auth_session: AuthSession,
        user: User,
        now: datetime,
    ) -> Optional[str]:
        if auth_session.absolute_expires_at <= now:
            return "absolute_expired"
        if auth_session.idle_expires_at <= now:
            return "idle_expired"
        if auth_session.auth_version != user.auth_version:
            return "auth_version_changed"
        if (
            user.status != "active"
            or user.deleted_at is not None
            or user.suspended_at is not None
            or user.email_verified_at is None
        ):
            return "account_unavailable"
        return None

    @staticmethod
    def _idle_lifetime(auth_session: AuthSession) -> timedelta:
        absolute_lifetime = auth_session.absolute_expires_at - auth_session.created_at
        if absolute_lifetime > timedelta(days=settings.AUTH_SESSION_ABSOLUTE_DAYS):
            return timedelta(days=settings.AUTH_REMEMBER_IDLE_DAYS)
        return timedelta(hours=settings.AUTH_SESSION_IDLE_HOURS)

    @staticmethod
    def _session_summary(
        auth_session: AuthSession,
        *,
        is_current: bool,
    ) -> SessionSummary:
        return SessionSummary(
            id=auth_session.id,
            auth_method=auth_session.auth_method,
            device_label=auth_session.device_label or "未知设备",
            created_at=auth_session.created_at,
            last_seen_at=auth_session.last_seen_at,
            idle_expires_at=auth_session.idle_expires_at,
            absolute_expires_at=auth_session.absolute_expires_at,
            is_current=is_current,
            location_label=SessionService._location_label(
                auth_session.last_ip or auth_session.created_ip
            ),
        )

    @staticmethod
    def _location_label(packed_address: Optional[bytes]) -> Optional[str]:
        if not packed_address:
            return None
        try:
            address = ip_address(packed_address)
        except ValueError:
            return None
        if address.is_loopback:
            return "本机"
        if address.is_private or address.is_link_local:
            return "本地网络"
        return None


def _is_bounded_token(raw_token: Optional[str]) -> bool:
    return bool(raw_token and 20 <= len(raw_token) <= 256)
