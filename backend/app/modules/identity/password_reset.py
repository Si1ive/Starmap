"""Single-use password reset issuance and consumption."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.types import new_uuid7
from app.modules.identity.context import AuthRequestContext
from app.modules.identity.models import (
    AuthActionToken,
    AuthEvent,
    AuthSession,
    PasswordCredential,
    User,
    utc_now,
)
from app.modules.identity.schemas import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.modules.identity.security import (
    PasswordPolicyError,
    PasswordService,
    action_token_digest,
    generate_opaque_token,
    identifier_digest,
    normalize_email,
    pack_ip_address,
    sanitize_user_agent,
)

RESET_PASSWORD_PURPOSE = "reset_password"
RESET_PASSWORD_TOKEN_DIGEST_PURPOSE = "reset_password:link"


class PasswordResetFlowError(ValueError):
    """A user-safe password-reset failure."""

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
class PasswordResetDelivery:
    """Plaintext reset credential retained only until email enqueue."""

    recipient: str
    challenge_id: uuid.UUID
    token: str


@dataclass(frozen=True)
class PasswordResetRequestOutcome:
    """Generic public request result plus an optional private delivery."""

    delivery: Optional[PasswordResetDelivery]


@dataclass(frozen=True)
class PasswordResetOutcome:
    """Successful reset metadata needed for the notification email."""

    recipient: str
    challenge_id: uuid.UUID


class PasswordResetService:
    """Issue and atomically consume password-reset credentials."""

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

    async def request_reset(
        self,
        payload: ForgotPasswordRequest,
        context: AuthRequestContext,
    ) -> PasswordResetRequestOutcome:
        """Return one generic result without revealing account existence."""

        normalized_email = self._normalize_email(payload.email)
        identifier = normalized_email or self._fallback_identifier(payload.email)
        user = None
        if normalized_email is not None:
            user = await self.db.scalar(
                select(User)
                .options(selectinload(User.password_credential))
                .where(User.email_normalized == normalized_email)
                .with_for_update()
            )

        if not self._can_reset(
            user,
            user.password_credential if user is not None else None,
        ):
            self._record_event(
                event_type="password_reset_request",
                outcome="accepted",
                user_id=user.id if user else None,
                identifier=identifier,
                context=context,
                reason_code="account_not_eligible",
            )
            await self.db.commit()
            return PasswordResetRequestOutcome(delivery=None)

        now = self.clock()
        await self.db.execute(
            update(AuthActionToken)
            .where(
                AuthActionToken.user_id == user.id,
                AuthActionToken.purpose == RESET_PASSWORD_PURPOSE,
                AuthActionToken.consumed_at.is_(None),
                AuthActionToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
            .execution_options(synchronize_session="fetch")
        )
        challenge_id = new_uuid7()
        raw_token = generate_opaque_token()
        self.db.add(
            AuthActionToken(
                id=new_uuid7(),
                user_id=user.id,
                purpose=RESET_PASSWORD_PURPOSE,
                challenge_id=challenge_id,
                token_kind="link",
                token_hash=action_token_digest(
                    raw_token,
                    RESET_PASSWORD_TOKEN_DIGEST_PURPOSE,
                ),
                key_version=settings.AUTH_ACTION_TOKEN_KEY_VERSION,
                target_value=user.email_normalized,
                request_ip=pack_ip_address(context.remote_ip),
                metadata_json={"auth_version": user.auth_version},
                created_at=now,
                expires_at=now
                + timedelta(minutes=settings.AUTH_PASSWORD_RESET_MINUTES),
            )
        )
        self._record_event(
            event_type="password_reset_request",
            outcome="success",
            user_id=user.id,
            identifier=identifier,
            context=context,
        )
        await self.db.commit()
        return PasswordResetRequestOutcome(
            delivery=PasswordResetDelivery(
                recipient=user.email_display or user.email_normalized,
                challenge_id=challenge_id,
                token=raw_token,
            )
        )

    async def reset_password(
        self,
        payload: ResetPasswordRequest,
        context: AuthRequestContext,
    ) -> PasswordResetOutcome:
        """Consume one token, rotate the password, and revoke all sessions."""

        if payload.password != payload.password_confirmation:
            raise PasswordResetFlowError(
                "PASSWORD_CONFIRMATION_MISMATCH",
                "两次输入的密码不一致",
            )
        try:
            password_hash = self.password_service.hash_password(payload.password)
        except PasswordPolicyError as exc:
            raise PasswordResetFlowError(exc.code, str(exc)) from exc

        token_hash = action_token_digest(
            payload.token,
            RESET_PASSWORD_TOKEN_DIGEST_PURPOSE,
        )
        candidate = await self.db.scalar(
            select(AuthActionToken).where(
                AuthActionToken.purpose == RESET_PASSWORD_PURPOSE,
                AuthActionToken.token_kind == "link",
                AuthActionToken.token_hash == token_hash,
            )
        )
        if candidate is None or candidate.user_id is None:
            await self._reject_reset(context)

        user = await self.db.scalar(
            select(User)
            .where(User.id == candidate.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        credential = await self.db.scalar(
            select(PasswordCredential)
            .where(PasswordCredential.user_id == candidate.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        token = await self.db.scalar(
            select(AuthActionToken)
            .where(
                AuthActionToken.id == candidate.id,
                AuthActionToken.token_hash == token_hash,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = self.clock()
        issued_auth_version = (
            token.metadata_json.get("auth_version")
            if token is not None and token.metadata_json
            else None
        )
        if (
            user is None
            or credential is None
            or not self._is_active(token, now)
            or token.user_id != user.id
            or token.target_value != user.email_normalized
            or issued_auth_version != user.auth_version
            or not self._can_reset(user, credential)
        ):
            await self._reject_reset(
                context,
                user_id=user.id if user is not None else None,
            )

        token.consumed_at = now
        await self.db.execute(
            update(AuthActionToken)
            .where(
                AuthActionToken.user_id == user.id,
                AuthActionToken.purpose == RESET_PASSWORD_PURPOSE,
                AuthActionToken.id != token.id,
                AuthActionToken.consumed_at.is_(None),
                AuthActionToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
            .execution_options(synchronize_session="fetch")
        )
        credential.password_hash = password_hash
        credential.hash_scheme = "argon2id"
        credential.password_changed_at = now
        credential.must_change = False
        credential.compromised_at = None
        credential.updated_at = now
        user.auth_version += 1
        user.updated_at = now
        user.row_version += 1
        await self.db.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
            .values(
                revoked_at=now,
                revoke_reason="password_reset",
            )
            .execution_options(synchronize_session="fetch")
        )
        self._record_event(
            event_type="password_reset",
            outcome="success",
            user_id=user.id,
            identifier=user.email_normalized,
            context=context,
        )
        await self.db.commit()
        return PasswordResetOutcome(
            recipient=user.email_display or user.email_normalized,
            challenge_id=token.challenge_id,
        )

    @staticmethod
    def _can_reset(
        user: Optional[User],
        credential: Optional[PasswordCredential],
    ) -> bool:
        return bool(
            user is not None
            and user.status == "active"
            and user.email_verified_at is not None
            and user.deleted_at is None
            and user.suspended_at is None
            and user.email_normalized
            and credential is not None
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

    async def _reject_reset(
        self,
        context: AuthRequestContext,
        *,
        user_id: Optional[uuid.UUID] = None,
    ) -> None:
        await self.db.rollback()
        self._record_event(
            event_type="password_reset",
            outcome="failure",
            user_id=user_id,
            identifier=None,
            context=context,
            reason_code="invalid_or_expired_token",
        )
        await self.db.commit()
        raise PasswordResetFlowError(
            "PASSWORD_RESET_INVALID",
            "重置凭据无效或已过期",
        )

    def _record_event(
        self,
        *,
        event_type: str,
        outcome: str,
        user_id: Optional[uuid.UUID],
        identifier: Optional[str],
        context: AuthRequestContext,
        reason_code: Optional[str] = None,
    ) -> None:
        self.db.add(
            AuthEvent(
                user_id=user_id,
                event_type=event_type,
                outcome=outcome,
                provider="password",
                reason_code=reason_code,
                identifier_hmac=(identifier_digest(identifier) if identifier else None),
                ip_address=pack_ip_address(context.remote_ip),
                user_agent=sanitize_user_agent(context.user_agent),
                request_id=(context.request_id or "")[:64] or None,
            )
        )

    @staticmethod
    def _normalize_email(value: str) -> Optional[str]:
        try:
            normalized, _ = normalize_email(value)
        except ValueError:
            return None
        return normalized

    @staticmethod
    def _fallback_identifier(value: str) -> str:
        return value.strip().casefold()[:320] or "invalid-email"
