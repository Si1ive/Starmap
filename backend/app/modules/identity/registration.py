"""Email registration and single-use verification transactions."""

from __future__ import annotations

import hmac
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
from app.modules.identity.models import (
    AuthActionToken,
    AuthEvent,
    PasswordCredential,
    User,
    UserConsent,
    UserProfile,
    utc_now,
)
from app.modules.identity.schemas import (
    ConfirmEmailVerificationRequest,
    RegisterRequest,
)
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

VERIFY_EMAIL_PURPOSE = "verify_email"
VERIFY_EMAIL_LINK_DIGEST_PURPOSE = "verify_email:link"
VERIFY_EMAIL_CODE_DIGEST_PURPOSE = "verify_email:code"
VERIFY_EMAIL_TRANSACTION_DIGEST_PURPOSE = "verify_email:transaction"


class RegistrationFlowError(ValueError):
    """A user-safe registration or email-verification failure."""

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
class AuthRequestContext:
    """Bounded request metadata persisted for authentication auditing."""

    remote_ip: Optional[str]
    user_agent: Optional[str]
    request_id: Optional[str]


@dataclass(frozen=True)
class VerificationDelivery:
    """Plaintext credentials that exist only until the email is queued."""

    recipient: str
    challenge_id: uuid.UUID
    transaction_token: str
    link_token: str
    code: str


@dataclass(frozen=True)
class RegistrationOutcome:
    """Generic public result plus an optional private delivery task."""

    registration_token: str
    delivery: Optional[VerificationDelivery]


@dataclass(frozen=True)
class EmailVerificationOutcome:
    """Activated user details returned after a challenge is consumed."""

    user_id: uuid.UUID
    email: str
    display_name: str
    same_browser: bool


class RegistrationService:
    """Own pending accounts and atomic email-verification challenges."""

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

    async def register(
        self,
        payload: RegisterRequest,
        context: AuthRequestContext,
    ) -> RegistrationOutcome:
        """Create a pending account or safely resume its verification."""

        normalized_email, display_email = self._validate_registration(payload)
        existing = await self.db.scalar(
            select(User)
            .options(
                selectinload(User.profile),
                selectinload(User.password_credential),
            )
            .where(User.email_normalized == normalized_email)
            .with_for_update()
        )
        if existing is not None:
            return await self._handle_existing_registration(
                existing,
                payload,
                normalized_email,
                context,
            )

        now = self.clock()
        user_id = new_uuid7()
        password_hash = self.password_service.hash_password(payload.password)
        user = User(
            id=user_id,
            email_normalized=normalized_email,
            email_display=display_email,
            status="pending_email",
            created_at=now,
            updated_at=now,
        )
        user.profile = UserProfile(
            user_id=user_id,
            display_name=payload.display_name,
            created_at=now,
            updated_at=now,
        )
        user.password_credential = PasswordCredential(
            user_id=user_id,
            password_hash=password_hash,
            password_changed_at=now,
            created_at=now,
            updated_at=now,
        )
        self.db.add(user)
        self.db.add_all(
            [
                UserConsent(
                    user_id=user_id,
                    document_type="terms",
                    document_version=settings.AUTH_TERMS_VERSION,
                    accepted_at=now,
                    ip_address=pack_ip_address(context.remote_ip),
                    source="register",
                ),
                UserConsent(
                    user_id=user_id,
                    document_type="privacy",
                    document_version=settings.AUTH_PRIVACY_VERSION,
                    accepted_at=now,
                    ip_address=pack_ip_address(context.remote_ip),
                    source="register",
                ),
            ]
        )
        delivery = await self._issue_verification_challenge(
            user,
            normalized_email,
            context,
            now,
        )
        self._record_event(
            event_type="register",
            outcome="success",
            user_id=user_id,
            normalized_email=normalized_email,
            context=context,
        )

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            return self._generic_outcome()
        return RegistrationOutcome(
            registration_token=delivery.transaction_token,
            delivery=delivery,
        )

    async def resend(
        self,
        registration_token: Optional[str],
        context: AuthRequestContext,
    ) -> RegistrationOutcome:
        """Rotate a valid pending registration challenge."""

        if not registration_token:
            return self._generic_outcome()

        now = self.clock()
        candidate = await self._find_action_token(
            registration_token,
            VERIFY_EMAIL_TRANSACTION_DIGEST_PURPOSE,
            token_kind="transaction",
            for_update=False,
        )
        if candidate is None or candidate.user_id is None:
            await self.db.rollback()
            return self._generic_outcome()

        user = await self.db.scalar(
            select(User).where(User.id == candidate.user_id).with_for_update()
        )
        transaction = await self._find_action_token(
            registration_token,
            VERIFY_EMAIL_TRANSACTION_DIGEST_PURPOSE,
            token_kind="transaction",
        )
        if (
            user is None
            or not self._is_active(transaction, now)
            or transaction.user_id != user.id
            or user.status != "pending_email"
            or user.deleted_at is not None
            or not user.email_normalized
        ):
            await self.db.rollback()
            return self._generic_outcome()

        delivery = await self._issue_verification_challenge(
            user,
            user.email_normalized,
            context,
            now,
        )
        self._record_event(
            event_type="verification_resend",
            outcome="success",
            user_id=user.id,
            normalized_email=user.email_normalized,
            context=context,
        )
        await self.db.commit()
        return RegistrationOutcome(
            registration_token=delivery.transaction_token,
            delivery=delivery,
        )

    async def confirm_email(
        self,
        payload: ConfirmEmailVerificationRequest,
        registration_token: Optional[str],
        context: AuthRequestContext,
    ) -> EmailVerificationOutcome:
        """Consume a link or browser-bound code and activate the account."""

        now = self.clock()
        same_browser = False
        if payload.code is not None:
            candidate = await self._find_action_token(
                registration_token,
                VERIFY_EMAIL_TRANSACTION_DIGEST_PURPOSE,
                token_kind="transaction",
                for_update=False,
            )
            if candidate is None or candidate.user_id is None:
                await self._reject_verification()
            user = await self._lock_user(candidate.user_id)
            transaction = await self._find_action_token(
                registration_token,
                VERIFY_EMAIL_TRANSACTION_DIGEST_PURPOSE,
                token_kind="transaction",
            )
            if (
                user is None
                or not self._is_active(transaction, now)
                or transaction.user_id != user.id
            ):
                await self._reject_verification()
            presented = await self.db.scalar(
                select(AuthActionToken)
                .where(
                    AuthActionToken.challenge_id == transaction.challenge_id,
                    AuthActionToken.purpose == VERIFY_EMAIL_PURPOSE,
                    AuthActionToken.token_kind == "code",
                )
                .with_for_update()
            )
            if not self._is_active(presented, now):
                await self._reject_verification()
            candidate_hash = action_token_digest(
                payload.code,
                VERIFY_EMAIL_CODE_DIGEST_PURPOSE,
            )
            if not hmac.compare_digest(candidate_hash, presented.token_hash):
                await self._record_failed_code(presented, context, now)
                raise RegistrationFlowError(
                    "VERIFICATION_INVALID",
                    "验证凭据无效或已过期",
                )
            same_browser = True
        else:
            candidate = await self._find_action_token(
                payload.token,
                VERIFY_EMAIL_LINK_DIGEST_PURPOSE,
                token_kind="link",
                for_update=False,
            )
            if candidate is None or candidate.user_id is None:
                await self._reject_verification()
            user = await self._lock_user(candidate.user_id)
            presented = await self._find_action_token(
                payload.token,
                VERIFY_EMAIL_LINK_DIGEST_PURPOSE,
                token_kind="link",
            )
            if (
                user is None
                or not self._is_active(presented, now)
                or presented.user_id != user.id
            ):
                await self._reject_verification()
            same_browser = await self._matches_browser_transaction(
                presented.challenge_id,
                registration_token,
                now,
            )

        if presented.user_id is None:
            await self._reject_verification()
        if (
            user is None
            or user.status != "pending_email"
            or user.deleted_at is not None
            or not user.email_normalized
            or presented.target_value != user.email_normalized
        ):
            await self._reject_verification()

        presented.consumed_at = now
        await self.db.execute(
            update(AuthActionToken)
            .where(
                AuthActionToken.challenge_id == presented.challenge_id,
                AuthActionToken.id != presented.id,
            )
            .values(invalidated_at=now)
            .execution_options(synchronize_session="fetch")
        )
        user.email_verified_at = now
        user.status = "active"
        user.activated_at = user.activated_at or now
        user.updated_at = now
        user.row_version += 1
        self._record_event(
            event_type="email_verification",
            outcome="success",
            user_id=user.id,
            normalized_email=user.email_normalized,
            context=context,
        )
        await self.db.commit()

        return EmailVerificationOutcome(
            user_id=user.id,
            email=user.email_display or user.email_normalized,
            display_name=user.profile.display_name if user.profile else "",
            same_browser=same_browser,
        )

    def _validate_registration(
        self,
        payload: RegisterRequest,
    ) -> tuple[str, str]:
        if payload.password != payload.password_confirmation:
            raise RegistrationFlowError(
                "PASSWORD_CONFIRMATION_MISMATCH",
                "两次输入的密码不一致",
            )
        if not payload.accept_terms or not payload.accept_privacy:
            raise RegistrationFlowError(
                "CONSENT_REQUIRED",
                "必须同意服务条款和隐私说明",
            )
        try:
            normalized_email, display_email = normalize_email(str(payload.email))
            self.password_service.validate_new_password(payload.password)
        except PasswordPolicyError as exc:
            raise RegistrationFlowError(exc.code, str(exc)) from exc
        except ValueError as exc:
            raise RegistrationFlowError("EMAIL_INVALID", str(exc)) from exc
        return normalized_email, display_email

    async def _handle_existing_registration(
        self,
        user: User,
        payload: RegisterRequest,
        normalized_email: str,
        context: AuthRequestContext,
    ) -> RegistrationOutcome:
        credential = user.password_credential
        password_hash = credential.password_hash if credential else None
        verification = self.password_service.verify_password(
            payload.password,
            password_hash,
        )
        can_resume = (
            verification.valid
            and credential is not None
            and user.status == "pending_email"
            and user.deleted_at is None
        )
        if not can_resume:
            self._record_event(
                event_type="register",
                outcome="denied",
                user_id=user.id,
                normalized_email=normalized_email,
                context=context,
                reason_code="existing_account",
            )
            await self.db.commit()
            return self._generic_outcome()

        now = self.clock()
        if verification.updated_hash:
            credential.password_hash = verification.updated_hash
            credential.updated_at = now
        if user.profile is not None:
            user.profile.display_name = payload.display_name
            user.profile.updated_at = now
        delivery = await self._issue_verification_challenge(
            user,
            normalized_email,
            context,
            now,
        )
        self._record_event(
            event_type="verification_resend",
            outcome="success",
            user_id=user.id,
            normalized_email=normalized_email,
            context=context,
            reason_code="registration_resumed",
        )
        await self.db.commit()
        return RegistrationOutcome(
            registration_token=delivery.transaction_token,
            delivery=delivery,
        )

    async def _issue_verification_challenge(
        self,
        user: User,
        normalized_email: str,
        context: AuthRequestContext,
        now: datetime,
    ) -> VerificationDelivery:
        await self.db.execute(
            update(AuthActionToken)
            .where(
                AuthActionToken.user_id == user.id,
                AuthActionToken.purpose == VERIFY_EMAIL_PURPOSE,
                AuthActionToken.consumed_at.is_(None),
                AuthActionToken.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
            .execution_options(synchronize_session="fetch")
        )
        challenge_id = new_uuid7()
        transaction_token = generate_opaque_token()
        link_token = generate_opaque_token()
        code = generate_verification_code()
        request_ip = pack_ip_address(context.remote_ip)
        common = {
            "user_id": user.id,
            "purpose": VERIFY_EMAIL_PURPOSE,
            "challenge_id": challenge_id,
            "key_version": settings.AUTH_ACTION_TOKEN_KEY_VERSION,
            "target_value": normalized_email,
            "request_ip": request_ip,
            "created_at": now,
        }
        self.db.add_all(
            [
                AuthActionToken(
                    id=new_uuid7(),
                    token_kind="link",
                    token_hash=action_token_digest(
                        link_token,
                        VERIFY_EMAIL_LINK_DIGEST_PURPOSE,
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
                        VERIFY_EMAIL_CODE_DIGEST_PURPOSE,
                    ),
                    max_attempts=settings.AUTH_EMAIL_VERIFY_MAX_ATTEMPTS,
                    expires_at=now
                    + timedelta(minutes=settings.AUTH_EMAIL_VERIFY_CODE_MINUTES),
                    **common,
                ),
                AuthActionToken(
                    id=new_uuid7(),
                    token_kind="transaction",
                    token_hash=action_token_digest(
                        transaction_token,
                        VERIFY_EMAIL_TRANSACTION_DIGEST_PURPOSE,
                    ),
                    expires_at=now
                    + timedelta(minutes=settings.AUTH_REGISTRATION_TRANSACTION_MINUTES),
                    **common,
                ),
            ]
        )
        return VerificationDelivery(
            recipient=user.email_display or normalized_email,
            challenge_id=challenge_id,
            transaction_token=transaction_token,
            link_token=link_token,
            code=code,
        )

    async def _find_action_token(
        self,
        raw_token: Optional[str],
        digest_purpose: str,
        *,
        token_kind: str,
        for_update: bool = True,
    ) -> Optional[AuthActionToken]:
        if not raw_token:
            return None
        token_hash = action_token_digest(raw_token, digest_purpose)
        statement = select(AuthActionToken).where(
            AuthActionToken.purpose == VERIFY_EMAIL_PURPOSE,
            AuthActionToken.token_kind == token_kind,
            AuthActionToken.token_hash == token_hash,
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return await self.db.scalar(statement)

    async def _lock_user(self, user_id: uuid.UUID) -> Optional[User]:
        return await self.db.scalar(
            select(User)
            .options(selectinload(User.profile))
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def _matches_browser_transaction(
        self,
        challenge_id: uuid.UUID,
        raw_token: Optional[str],
        now: datetime,
    ) -> bool:
        if not raw_token:
            return False
        token_hash = action_token_digest(
            raw_token,
            VERIFY_EMAIL_TRANSACTION_DIGEST_PURPOSE,
        )
        transaction = await self.db.scalar(
            select(AuthActionToken)
            .where(
                AuthActionToken.challenge_id == challenge_id,
                AuthActionToken.token_kind == "transaction",
                AuthActionToken.token_hash == token_hash,
            )
            .with_for_update()
        )
        return self._is_active(transaction, now)

    async def _record_failed_code(
        self,
        token: AuthActionToken,
        context: AuthRequestContext,
        now: datetime,
    ) -> None:
        token.failed_attempts += 1
        if token.failed_attempts >= (
            token.max_attempts or settings.AUTH_EMAIL_VERIFY_MAX_ATTEMPTS
        ):
            token.invalidated_at = now
        self._record_event(
            event_type="email_verification",
            outcome="failure",
            user_id=token.user_id,
            normalized_email=token.target_value,
            context=context,
            reason_code="invalid_code",
        )
        await self.db.commit()

    def _record_event(
        self,
        *,
        event_type: str,
        outcome: str,
        user_id: Optional[uuid.UUID],
        normalized_email: Optional[str],
        context: AuthRequestContext,
        reason_code: Optional[str] = None,
    ) -> None:
        self.db.add(
            AuthEvent(
                user_id=user_id,
                event_type=event_type,
                outcome=outcome,
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

    async def _reject_verification(self) -> None:
        await self.db.rollback()
        raise RegistrationFlowError(
            "VERIFICATION_INVALID",
            "验证凭据无效或已过期",
        )

    @staticmethod
    def _generic_outcome() -> RegistrationOutcome:
        return RegistrationOutcome(
            registration_token=generate_opaque_token(),
            delivery=None,
        )
