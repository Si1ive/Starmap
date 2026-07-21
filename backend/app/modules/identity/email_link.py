"""Authenticated email-login binding with single-use verification."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.types import new_uuid7
from app.modules.identity.context import AuthRequestContext
from app.modules.identity.models import (
    AuthActionToken,
    AuthEvent,
    PasswordCredential,
    User,
    utc_now,
)
from app.modules.identity.schemas import ConfirmEmailLinkRequest, StartEmailLinkRequest
from app.modules.identity.security import (
    PasswordPolicyError,
    PasswordService,
    action_token_digest,
    generate_opaque_token,
    generate_verification_code,
    identifier_digest,
    normalize_email,
    pack_ip_address,
    sanitize_user_agent,
)
from app.modules.identity.session import AuthenticatedSession

LINK_EMAIL_PURPOSE = "link_email"


class EmailLinkFlowError(ValueError):
    """A user-safe email-login binding failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
    ) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class EmailLinkDelivery:
    """Plaintext verification credentials retained only until email enqueue."""

    recipient: str
    challenge_id: uuid.UUID
    link_token: str
    code: str


@dataclass(frozen=True)
class EmailLinkOutcome:
    """Completed email-login binding data."""

    email: str


class EmailLinkService:
    """Stage and atomically confirm an email-login credential."""

    def __init__(
        self,
        db: AsyncSession,
        password_service: PasswordService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.password_service = password_service
        self.clock = clock

    async def start(
        self,
        payload: StartEmailLinkRequest,
        current: AuthenticatedSession,
        context: AuthRequestContext,
    ) -> EmailLinkDelivery:
        """Validate the requested credential and issue verification tokens."""

        try:
            normalized_email, display_email = normalize_email(str(payload.email))
        except ValueError as exc:
            raise EmailLinkFlowError(
                "EMAIL_LINK_INVALID",
                "请输入有效邮箱",
            ) from exc
        try:
            password_hash = self.password_service.hash_password(payload.password)
        except PasswordPolicyError as exc:
            raise EmailLinkFlowError(exc.code, str(exc)) from exc

        user = await self._lock_user(current.user.id)
        self._ensure_eligible(user)
        if user.password_credential is not None:
            raise EmailLinkFlowError(
                "EMAIL_LOGIN_ALREADY_ENABLED",
                "当前账户已经启用邮箱登录",
                status_code=409,
            )
        if await self._email_owned_by_another_user(normalized_email, user.id):
            raise EmailLinkFlowError(
                "EMAIL_LINK_UNAVAILABLE",
                "该邮箱无法绑定到当前账户",
                status_code=409,
            )

        now = self.clock()
        await self.db.execute(
            update(AuthActionToken)
            .where(
                AuthActionToken.user_id == user.id,
                AuthActionToken.purpose == LINK_EMAIL_PURPOSE,
                AuthActionToken.consumed_at.is_(None),
                AuthActionToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
            .execution_options(synchronize_session="fetch")
        )
        challenge_id = new_uuid7()
        link_token = generate_opaque_token()
        code = generate_verification_code()
        metadata = {
            "password_hash": password_hash,
            "auth_version": user.auth_version,
            "display_email": display_email,
        }
        common = {
            "user_id": user.id,
            "purpose": LINK_EMAIL_PURPOSE,
            "challenge_id": challenge_id,
            "key_version": settings.AUTH_ACTION_TOKEN_KEY_VERSION,
            "target_value": normalized_email,
            "request_ip": pack_ip_address(context.remote_ip),
            "metadata_json": metadata,
            "created_at": now,
        }
        self.db.add_all(
            [
                AuthActionToken(
                    id=new_uuid7(),
                    token_kind="link",
                    token_hash=action_token_digest(
                        link_token,
                        self._link_digest_purpose(user.id),
                    ),
                    expires_at=now
                    + timedelta(minutes=settings.AUTH_EMAIL_VERIFY_LINK_MINUTES),
                    **common,
                ),
                AuthActionToken(
                    id=new_uuid7(),
                    token_kind="code",
                    token_hash=action_token_digest(
                        code,
                        self._code_digest_purpose(user.id),
                    ),
                    max_attempts=settings.AUTH_EMAIL_VERIFY_MAX_ATTEMPTS,
                    expires_at=now
                    + timedelta(minutes=settings.AUTH_EMAIL_VERIFY_CODE_MINUTES),
                    **common,
                ),
            ]
        )
        self._record_event(
            event_type="email_link_request",
            outcome="success",
            current=current,
            normalized_email=normalized_email,
            context=context,
        )
        await self.db.commit()
        return EmailLinkDelivery(
            recipient=display_email,
            challenge_id=challenge_id,
            link_token=link_token,
            code=code,
        )

    async def confirm(
        self,
        payload: ConfirmEmailLinkRequest,
        current: AuthenticatedSession,
        context: AuthRequestContext,
    ) -> EmailLinkOutcome:
        """Consume one verification credential and enable email login."""

        token = await self._find_token(payload, current.user.id)
        if token is None:
            if payload.code is not None:
                await self._record_failed_code(current, context)
            await self._reject(current, context)

        user = await self._lock_user(current.user.id)
        token = await self.db.scalar(
            select(AuthActionToken)
            .where(AuthActionToken.id == token.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = self.clock()
        metadata = token.metadata_json if token is not None else None
        password_hash = metadata.get("password_hash") if metadata else None
        issued_auth_version = metadata.get("auth_version") if metadata else None
        display_email = metadata.get("display_email") if metadata else None
        if (
            user is None
            or token is None
            or not self._is_active(token, now)
            or token.user_id != user.id
            or not token.target_value
            or not isinstance(password_hash, str)
            or not isinstance(display_email, str)
            or issued_auth_version != user.auth_version
        ):
            await self._reject(current, context)
        self._ensure_eligible(user)
        if user.password_credential is not None:
            await self.db.rollback()
            raise EmailLinkFlowError(
                "EMAIL_LOGIN_ALREADY_ENABLED",
                "当前账户已经启用邮箱登录",
                status_code=409,
            )
        if await self._email_owned_by_another_user(token.target_value, user.id):
            await self.db.rollback()
            raise EmailLinkFlowError(
                "EMAIL_LINK_UNAVAILABLE",
                "该邮箱无法绑定到当前账户",
                status_code=409,
            )

        token.consumed_at = now
        await self.db.execute(
            update(AuthActionToken)
            .where(
                AuthActionToken.challenge_id == token.challenge_id,
                AuthActionToken.id != token.id,
                AuthActionToken.consumed_at.is_(None),
                AuthActionToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
            .execution_options(synchronize_session="fetch")
        )
        user.email_normalized = token.target_value
        user.email_display = display_email
        user.email_verified_at = now
        user.updated_at = now
        user.row_version += 1
        user.password_credential = PasswordCredential(
            password_hash=password_hash,
            hash_scheme="argon2id",
            password_changed_at=now,
            must_change=False,
            created_at=now,
            updated_at=now,
        )
        self._record_event(
            event_type="identity_link",
            outcome="success",
            current=current,
            normalized_email=token.target_value,
            context=context,
            reason_code="email_ownership_verified",
        )
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise EmailLinkFlowError(
                "EMAIL_LINK_UNAVAILABLE",
                "该邮箱无法绑定到当前账户",
                status_code=409,
            ) from exc
        return EmailLinkOutcome(email=user.email_display or token.target_value)

    async def _find_token(
        self,
        payload: ConfirmEmailLinkRequest,
        user_id: uuid.UUID,
    ) -> Optional[AuthActionToken]:
        if payload.token is not None:
            token_kind = "link"
            token_hash = action_token_digest(
                payload.token,
                self._link_digest_purpose(user_id),
            )
        else:
            token_kind = "code"
            token_hash = action_token_digest(
                payload.code or "",
                self._code_digest_purpose(user_id),
            )
        return await self.db.scalar(
            select(AuthActionToken).where(
                AuthActionToken.user_id == user_id,
                AuthActionToken.purpose == LINK_EMAIL_PURPOSE,
                AuthActionToken.token_kind == token_kind,
                AuthActionToken.token_hash == token_hash,
            )
        )

    async def _record_failed_code(
        self,
        current: AuthenticatedSession,
        context: AuthRequestContext,
    ) -> None:
        now = self.clock()
        token = await self.db.scalar(
            select(AuthActionToken)
            .where(
                AuthActionToken.user_id == current.user.id,
                AuthActionToken.purpose == LINK_EMAIL_PURPOSE,
                AuthActionToken.token_kind == "code",
                AuthActionToken.consumed_at.is_(None),
                AuthActionToken.invalidated_at.is_(None),
                AuthActionToken.expires_at > now,
            )
            .order_by(AuthActionToken.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if token is None:
            return
        token.failed_attempts += 1
        if token.failed_attempts >= (
            token.max_attempts or settings.AUTH_EMAIL_VERIFY_MAX_ATTEMPTS
        ):
            token.invalidated_at = now
        self._record_event(
            event_type="email_link",
            outcome="failure",
            current=current,
            normalized_email=token.target_value,
            context=context,
            reason_code="invalid_code",
        )
        await self.db.commit()

    async def _reject(
        self,
        current: AuthenticatedSession,
        context: AuthRequestContext,
    ) -> None:
        await self.db.rollback()
        self._record_event(
            event_type="email_link",
            outcome="failure",
            current=current,
            normalized_email=None,
            context=context,
            reason_code="invalid_or_expired_token",
        )
        await self.db.commit()
        raise EmailLinkFlowError(
            "EMAIL_LINK_INVALID",
            "邮箱绑定凭据无效或已过期",
        )

    async def _lock_user(self, user_id: uuid.UUID) -> Optional[User]:
        return await self.db.scalar(
            select(User)
            .options(selectinload(User.password_credential))
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def _email_owned_by_another_user(
        self,
        normalized_email: str,
        user_id: uuid.UUID,
    ) -> bool:
        owner = await self.db.scalar(
            select(User.id).where(
                User.email_normalized == normalized_email,
                User.id != user_id,
            )
        )
        return owner is not None

    @staticmethod
    def _ensure_eligible(user: Optional[User]) -> None:
        if (
            user is None
            or user.status != "active"
            or user.deleted_at is not None
            or user.suspended_at is not None
        ):
            raise EmailLinkFlowError(
                "EMAIL_LINK_UNAVAILABLE",
                "当前账户无法绑定邮箱登录",
                status_code=409,
            )

    def _record_event(
        self,
        *,
        event_type: str,
        outcome: str,
        current: AuthenticatedSession,
        normalized_email: Optional[str],
        context: AuthRequestContext,
        reason_code: Optional[str] = None,
    ) -> None:
        self.db.add(
            AuthEvent(
                user_id=current.user.id,
                session_id=current.session.id,
                event_type=event_type,
                outcome=outcome,
                provider="password",
                reason_code=reason_code,
                identifier_hmac=(
                    identifier_digest(normalized_email) if normalized_email else None
                ),
                ip_address=pack_ip_address(context.remote_ip),
                user_agent=sanitize_user_agent(context.user_agent),
                request_id=(context.request_id or "")[:64] or None,
            )
        )

    @staticmethod
    def _is_active(
        token: Optional[AuthActionToken],
        now: datetime,
    ) -> bool:
        return bool(
            token is not None
            and token.consumed_at is None
            and token.invalidated_at is None
            and token.expires_at > now
        )

    @staticmethod
    def _link_digest_purpose(user_id: uuid.UUID) -> str:
        return f"{LINK_EMAIL_PURPOSE}:link:{user_id}"

    @staticmethod
    def _code_digest_purpose(user_id: uuid.UUID) -> str:
        return f"{LINK_EMAIL_PURPOSE}:code:{user_id}"
