"""Database integration tests for email registration and verification."""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.identity.models import (
    AuthActionToken,
    AuthEvent,
    AuthIdentity,
    AuthSession,
    PasswordCredential,
    User,
    UserConsent,
    UserProfile,
)
from app.modules.identity.registration import (
    AuthRequestContext,
    RegistrationFlowError,
    RegistrationService,
)
from app.modules.identity.schemas import (
    ConfirmEmailVerificationRequest,
    RegisterRequest,
)
from app.modules.identity.security import PasswordService

IDENTITY_TABLES = [
    User.__table__,
    UserProfile.__table__,
    AuthIdentity.__table__,
    PasswordCredential.__table__,
    AuthSession.__table__,
    AuthActionToken.__table__,
    AuthEvent.__table__,
    UserConsent.__table__,
]
NOW = datetime(2026, 7, 17, 8, 0, 0)
CONTEXT = AuthRequestContext(
    remote_ip="192.0.2.10",
    user_agent="Registration Test Browser",
    request_id="request-registration-test",
)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=IDENTITY_TABLES,
            )
        )
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_maker() as session:
        yield session
    await engine.dispose()


def registration_payload(
    *,
    password: str = "correct horse battery staple",
) -> RegisterRequest:
    return RegisterRequest(
        display_name="测试学习者",
        email="Learner@Example.com",
        password=password,
        password_confirmation=password,
        accept_terms=True,
        accept_privacy=True,
    )


@pytest.mark.asyncio
async def test_register_persists_only_digests_and_code_confirmation_is_atomic(
    db_session,
):
    service = RegistrationService(
        db_session,
        PasswordService(),
        clock=lambda: NOW,
    )

    outcome = await service.register(registration_payload(), CONTEXT)

    assert outcome.delivery is not None
    user = await db_session.scalar(select(User))
    assert user.status == "pending_email"
    assert user.email_normalized == "learner@example.com"
    assert user.password_credential.password_hash.startswith("$argon2id$")

    consents = (await db_session.scalars(select(UserConsent))).all()
    assert {consent.document_type for consent in consents} == {
        "terms",
        "privacy",
    }
    tokens = (await db_session.scalars(select(AuthActionToken))).all()
    assert {token.token_kind for token in tokens} == {
        "link",
        "code",
        "transaction",
    }
    assert all(len(token.token_hash) == 32 for token in tokens)
    plaintext_values = {
        outcome.delivery.link_token.encode(),
        outcome.delivery.code.encode(),
        outcome.delivery.transaction_token.encode(),
    }
    assert plaintext_values.isdisjoint({token.token_hash for token in tokens})

    verified = await service.confirm_email(
        ConfirmEmailVerificationRequest(code=outcome.delivery.code),
        outcome.registration_token,
        CONTEXT,
    )

    assert verified.user_id == user.id
    assert verified.same_browser
    refreshed_user = await db_session.get(User, user.id)
    assert refreshed_user.status == "active"
    assert refreshed_user.email_verified_at == NOW
    refreshed_tokens = (
        await db_session.scalars(
            select(AuthActionToken).where(
                AuthActionToken.challenge_id == outcome.delivery.challenge_id
            )
        )
    ).all()
    code_token = next(token for token in refreshed_tokens if token.token_kind == "code")
    assert code_token.consumed_at == NOW
    assert all(
        token.invalidated_at == NOW
        for token in refreshed_tokens
        if token.token_kind != "code"
    )

    with pytest.raises(RegistrationFlowError) as replayed:
        await service.confirm_email(
            ConfirmEmailVerificationRequest(code=outcome.delivery.code),
            outcome.registration_token,
            CONTEXT,
        )
    assert replayed.value.code == "VERIFICATION_INVALID"


@pytest.mark.asyncio
async def test_resend_invalidates_the_previous_challenge_and_link_is_single_use(
    db_session,
):
    service = RegistrationService(
        db_session,
        PasswordService(),
        clock=lambda: NOW,
    )
    first = await service.register(registration_payload(), CONTEXT)

    second = await service.resend(first.registration_token, CONTEXT)

    assert first.delivery is not None
    assert second.delivery is not None
    assert second.delivery.challenge_id != first.delivery.challenge_id
    first_tokens = (
        await db_session.scalars(
            select(AuthActionToken).where(
                AuthActionToken.challenge_id == first.delivery.challenge_id
            )
        )
    ).all()
    assert all(token.invalidated_at == NOW for token in first_tokens)

    with pytest.raises(RegistrationFlowError):
        await service.confirm_email(
            ConfirmEmailVerificationRequest(token=first.delivery.link_token),
            None,
            CONTEXT,
        )

    verified = await service.confirm_email(
        ConfirmEmailVerificationRequest(token=second.delivery.link_token),
        None,
        CONTEXT,
    )
    assert not verified.same_browser

    with pytest.raises(RegistrationFlowError):
        await service.confirm_email(
            ConfirmEmailVerificationRequest(token=second.delivery.link_token),
            None,
            CONTEXT,
        )


@pytest.mark.asyncio
async def test_verification_code_is_disabled_after_five_failed_attempts(
    db_session,
):
    service = RegistrationService(
        db_session,
        PasswordService(),
        clock=lambda: NOW,
    )
    outcome = await service.register(registration_payload(), CONTEXT)
    assert outcome.delivery is not None
    wrong_code = "000000" if outcome.delivery.code != "000000" else "000001"

    for _ in range(5):
        with pytest.raises(RegistrationFlowError) as failure:
            await service.confirm_email(
                ConfirmEmailVerificationRequest(code=wrong_code),
                outcome.registration_token,
                CONTEXT,
            )
        assert failure.value.code == "VERIFICATION_INVALID"

    code_token = await db_session.scalar(
        select(AuthActionToken).where(
            AuthActionToken.challenge_id == outcome.delivery.challenge_id,
            AuthActionToken.token_kind == "code",
        )
    )
    assert code_token.failed_attempts == 5
    assert code_token.invalidated_at == NOW

    with pytest.raises(RegistrationFlowError):
        await service.confirm_email(
            ConfirmEmailVerificationRequest(code=outcome.delivery.code),
            outcome.registration_token,
            CONTEXT,
        )


@pytest.mark.asyncio
async def test_duplicate_active_registration_returns_the_same_public_shape(
    db_session,
):
    service = RegistrationService(
        db_session,
        PasswordService(),
        clock=lambda: NOW,
    )
    first = await service.register(registration_payload(), CONTEXT)
    assert first.delivery is not None
    await service.confirm_email(
        ConfirmEmailVerificationRequest(token=first.delivery.link_token),
        first.registration_token,
        CONTEXT,
    )
    token_count = len((await db_session.scalars(select(AuthActionToken))).all())

    duplicate = await service.register(registration_payload(), CONTEXT)

    assert duplicate.delivery is None
    assert duplicate.registration_token
    assert duplicate.registration_token != first.registration_token
    assert len((await db_session.scalars(select(AuthActionToken))).all()) == token_count
