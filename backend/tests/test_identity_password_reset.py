"""Database integration tests for single-use password resets."""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.identity.context import AuthRequestContext
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
from app.modules.identity.password_reset import (
    PasswordResetFlowError,
    PasswordResetService,
    RESET_PASSWORD_PURPOSE,
    RESET_PASSWORD_TOKEN_DIGEST_PURPOSE,
)
from app.modules.identity.schemas import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.modules.identity.security import (
    PasswordService,
    action_token_digest,
    csrf_token_digest,
    derive_csrf_token,
    session_token_digest,
)

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
NOW = datetime(2026, 7, 17, 11, 0, 0)
OLD_PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a newly generated password phrase"
CONTEXT = AuthRequestContext(
    remote_ip="192.0.2.44",
    user_agent="Password Reset Test Browser",
    request_id="request-password-reset-test",
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


async def create_user(db_session, password_service):
    user = User(
        email_normalized="learner@example.com",
        email_display="Learner@example.com",
        email_verified_at=NOW,
        status="active",
        activated_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    user.profile = UserProfile(
        display_name="测试学习者",
        created_at=NOW,
        updated_at=NOW,
    )
    user.password_credential = PasswordCredential(
        password_hash=password_service.hash_password(OLD_PASSWORD),
        password_changed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def create_session(db_session, user, raw_token):
    session = AuthSession(
        user_id=user.id,
        token_hash=session_token_digest(raw_token),
        csrf_secret_hash=csrf_token_digest(derive_csrf_token(raw_token)),
        auth_version=user.auth_version,
        auth_method="password",
        created_at=NOW,
        last_seen_at=NOW,
        idle_expires_at=NOW + timedelta(hours=12),
        absolute_expires_at=NOW + timedelta(days=7),
    )
    db_session.add(session)
    await db_session.commit()
    return session


def forgot_request(email=" Learner@Example.com "):
    return ForgotPasswordRequest(email=email)


def reset_request(token, password=NEW_PASSWORD):
    return ResetPasswordRequest(
        token=token,
        password=password,
        password_confirmation=password,
    )


@pytest.mark.asyncio
async def test_request_reset_persists_only_digest_and_rotates_previous_token(
    db_session,
):
    password_service = PasswordService()
    user = await create_user(db_session, password_service)
    service = PasswordResetService(
        db_session,
        password_service,
        clock=lambda: NOW,
    )

    first = await service.request_reset(forgot_request(), CONTEXT)
    second = await service.request_reset(forgot_request(), CONTEXT)

    assert first.delivery is not None
    assert second.delivery is not None
    assert first.delivery.challenge_id != second.delivery.challenge_id
    tokens = (
        await db_session.scalars(
            select(AuthActionToken).where(
                AuthActionToken.user_id == user.id,
                AuthActionToken.purpose == RESET_PASSWORD_PURPOSE,
            )
        )
    ).all()
    first_token = next(
        token for token in tokens if token.challenge_id == first.delivery.challenge_id
    )
    second_token = next(
        token for token in tokens if token.challenge_id == second.delivery.challenge_id
    )
    assert first_token.invalidated_at == NOW
    assert second_token.invalidated_at is None
    assert second_token.expires_at == NOW + timedelta(minutes=30)
    assert second_token.token_hash == action_token_digest(
        second.delivery.token,
        RESET_PASSWORD_TOKEN_DIGEST_PURPOSE,
    )
    assert second.delivery.token.encode() != second_token.token_hash
    assert second_token.metadata_json == {"auth_version": user.auth_version}


@pytest.mark.asyncio
async def test_unknown_and_ineligible_accounts_return_no_delivery(db_session):
    password_service = PasswordService()
    user = await create_user(db_session, password_service)
    user.status = "suspended"
    user.suspended_at = NOW
    await db_session.commit()
    service = PasswordResetService(
        db_session,
        password_service,
        clock=lambda: NOW,
    )

    unknown = await service.request_reset(
        forgot_request("missing@example.com"),
        CONTEXT,
    )
    invalid = await service.request_reset(forgot_request("not-an-email"), CONTEXT)
    ineligible = await service.request_reset(forgot_request(), CONTEXT)

    assert unknown.delivery is None
    assert invalid.delivery is None
    assert ineligible.delivery is None
    assert await db_session.scalar(select(AuthActionToken)) is None
    events = (
        await db_session.scalars(
            select(AuthEvent).where(AuthEvent.event_type == "password_reset_request")
        )
    ).all()
    assert len(events) == 3
    assert all(event.outcome == "accepted" for event in events)
    assert all(event.identifier_hmac is not None for event in events)


@pytest.mark.asyncio
async def test_reset_changes_password_and_revokes_every_existing_session(db_session):
    password_service = PasswordService()
    user = await create_user(db_session, password_service)
    first_session = await create_session(
        db_session,
        user,
        "first-password-reset-session-token",
    )
    second_session = await create_session(
        db_session,
        user,
        "second-password-reset-session-token",
    )
    service = PasswordResetService(
        db_session,
        password_service,
        clock=lambda: NOW,
    )
    request_outcome = await service.request_reset(forgot_request(), CONTEXT)
    assert request_outcome.delivery is not None

    outcome = await service.reset_password(
        reset_request(request_outcome.delivery.token),
        CONTEXT,
    )

    assert outcome.recipient == "Learner@example.com"
    credential = await db_session.get(PasswordCredential, user.id)
    assert password_service.verify_password(
        NEW_PASSWORD,
        credential.password_hash,
    ).valid
    assert not password_service.verify_password(
        OLD_PASSWORD,
        credential.password_hash,
    ).valid
    assert credential.password_changed_at == NOW
    assert credential.must_change is False
    assert credential.compromised_at is None
    refreshed_user = await db_session.get(User, user.id)
    assert refreshed_user.auth_version == 2
    assert refreshed_user.row_version == 2
    for session in (first_session, second_session):
        await db_session.refresh(session)
        assert session.revoked_at == NOW
        assert session.revoke_reason == "password_reset"
    token = await db_session.scalar(
        select(AuthActionToken).where(
            AuthActionToken.challenge_id == request_outcome.delivery.challenge_id
        )
    )
    assert token.consumed_at == NOW
    event = await db_session.scalar(
        select(AuthEvent).where(AuthEvent.event_type == "password_reset")
    )
    assert event.outcome == "success"
    assert event.user_id == user.id

    with pytest.raises(PasswordResetFlowError) as replay:
        await service.reset_password(
            reset_request(request_outcome.delivery.token),
            CONTEXT,
        )
    assert replay.value.code == "PASSWORD_RESET_INVALID"


@pytest.mark.asyncio
async def test_expired_or_policy_rejected_reset_does_not_consume_token(db_session):
    password_service = PasswordService()
    await create_user(db_session, password_service)
    current_time = [NOW]
    service = PasswordResetService(
        db_session,
        password_service,
        clock=lambda: current_time[0],
    )
    request_outcome = await service.request_reset(forgot_request(), CONTEXT)
    assert request_outcome.delivery is not None

    with pytest.raises(PasswordResetFlowError) as weak_password:
        await service.reset_password(
            reset_request(request_outcome.delivery.token, "too short"),
            CONTEXT,
        )
    assert weak_password.value.code == "PASSWORD_TOO_SHORT"

    current_time[0] = NOW + timedelta(minutes=31)
    with pytest.raises(PasswordResetFlowError) as expired:
        await service.reset_password(
            reset_request(request_outcome.delivery.token),
            CONTEXT,
        )
    assert expired.value.code == "PASSWORD_RESET_INVALID"
    token = await db_session.scalar(
        select(AuthActionToken).where(
            AuthActionToken.challenge_id == request_outcome.delivery.challenge_id
        )
    )
    assert token.consumed_at is None


@pytest.mark.asyncio
async def test_auth_version_change_invalidates_an_outstanding_reset(db_session):
    password_service = PasswordService()
    user = await create_user(db_session, password_service)
    service = PasswordResetService(
        db_session,
        password_service,
        clock=lambda: NOW,
    )
    request_outcome = await service.request_reset(forgot_request(), CONTEXT)
    assert request_outcome.delivery is not None
    user_id = user.id
    user.auth_version += 1
    await db_session.commit()

    with pytest.raises(PasswordResetFlowError) as stale:
        await service.reset_password(
            reset_request(request_outcome.delivery.token),
            CONTEXT,
        )

    assert stale.value.code == "PASSWORD_RESET_INVALID"
    credential = await db_session.get(PasswordCredential, user_id)
    assert password_service.verify_password(
        OLD_PASSWORD,
        credential.password_hash,
    ).valid
    token = await db_session.scalar(
        select(AuthActionToken).where(
            AuthActionToken.challenge_id == request_outcome.delivery.challenge_id
        )
    )
    assert token.consumed_at is None
