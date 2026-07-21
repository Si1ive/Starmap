"""Database integration tests for authenticated email-login binding."""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.identity.context import AuthRequestContext
from app.modules.identity.email_link import (
    LINK_EMAIL_PURPOSE,
    EmailLinkFlowError,
    EmailLinkService,
)
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
from app.modules.identity.schemas import ConfirmEmailLinkRequest, StartEmailLinkRequest
from app.modules.identity.security import PasswordService
from app.modules.identity.session import AuthenticatedSession

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
NOW = datetime(2026, 7, 18, 9, 0, 0)
PASSWORD = "a private email login password"
CONTEXT = AuthRequestContext(
    remote_ip="192.0.2.88",
    user_agent="Email Link Test Browser",
    request_id="request-email-link-test",
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


async def create_github_session(db_session) -> AuthenticatedSession:
    user = User(
        email_normalized="github-contact@example.com",
        email_display="github-contact@example.com",
        email_verified_at=NOW,
        status="active",
        auth_version=1,
        activated_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    user.profile = UserProfile(
        display_name="GitHub 学习者",
        created_at=NOW,
        updated_at=NOW,
    )
    user.identities.append(
        AuthIdentity(
            provider="github",
            provider_subject="github-user-42",
            provider_username="learner",
            provider_email="github-contact@example.com",
            provider_email_verified=True,
            linked_at=NOW,
            updated_at=NOW,
        )
    )
    auth_session = AuthSession(
        token_hash=b"s" * 32,
        csrf_secret_hash=b"c" * 32,
        auth_version=user.auth_version,
        auth_method="github",
        device_label="Chrome on macOS",
        created_at=NOW,
        last_seen_at=NOW,
        idle_expires_at=NOW + timedelta(hours=12),
        absolute_expires_at=NOW + timedelta(days=7),
    )
    user.sessions.append(auth_session)
    db_session.add(user)
    await db_session.commit()
    return AuthenticatedSession(
        user=user,
        profile=user.profile,
        session=auth_session,
        csrf_token="csrf-token",
    )


def start_payload(
    email: str = "Study.Login@Example.com",
) -> StartEmailLinkRequest:
    return StartEmailLinkRequest(
        email=email,
        password=PASSWORD,
        password_confirmation=PASSWORD,
    )


@pytest.mark.asyncio
async def test_github_contact_email_is_not_bound_until_code_confirmation(
    db_session,
):
    current = await create_github_session(db_session)
    password_service = PasswordService()
    service = EmailLinkService(
        db_session,
        password_service,
        clock=lambda: NOW,
    )

    delivery = await service.start(start_payload(), current, CONTEXT)

    assert delivery.recipient == "Study.Login@example.com"
    assert await db_session.get(PasswordCredential, current.user.id) is None
    assert current.user.email_display == "github-contact@example.com"
    tokens = (
        await db_session.scalars(
            select(AuthActionToken).where(
                AuthActionToken.user_id == current.user.id,
                AuthActionToken.purpose == LINK_EMAIL_PURPOSE,
            )
        )
    ).all()
    assert {token.token_kind for token in tokens} == {"link", "code"}
    assert all(token.target_value == "study.login@example.com" for token in tokens)
    assert all(
        token.metadata_json["display_email"] == "Study.Login@example.com"
        for token in tokens
    )
    assert all(delivery.code.encode() != token.token_hash for token in tokens)
    assert all(delivery.link_token.encode() != token.token_hash for token in tokens)

    outcome = await service.confirm(
        ConfirmEmailLinkRequest(code=delivery.code),
        current,
        CONTEXT,
    )

    assert outcome.email == "Study.Login@example.com"
    credential = await db_session.get(PasswordCredential, current.user.id)
    assert credential is not None
    assert password_service.verify_password(
        PASSWORD,
        credential.password_hash,
    ).valid
    refreshed_user = await db_session.get(User, current.user.id)
    assert refreshed_user.email_normalized == "study.login@example.com"
    assert refreshed_user.email_display == "Study.Login@example.com"
    assert refreshed_user.email_verified_at == NOW
    assert refreshed_user.auth_version == 1
    assert refreshed_user.row_version == 2
    linked_identity = await db_session.scalar(
        select(AuthIdentity).where(AuthIdentity.user_id == current.user.id)
    )
    assert linked_identity.provider_email == "github-contact@example.com"
    refreshed_tokens = (
        await db_session.scalars(
            select(AuthActionToken).where(
                AuthActionToken.challenge_id == delivery.challenge_id
            )
        )
    ).all()
    code_token = next(token for token in refreshed_tokens if token.token_kind == "code")
    link_token = next(token for token in refreshed_tokens if token.token_kind == "link")
    assert code_token.consumed_at == NOW
    assert link_token.invalidated_at == NOW


@pytest.mark.asyncio
async def test_invalid_code_does_not_create_a_password_credential(db_session):
    current = await create_github_session(db_session)
    service = EmailLinkService(
        db_session,
        PasswordService(),
        clock=lambda: NOW,
    )
    delivery = await service.start(start_payload(), current, CONTEXT)
    invalid_code = "000000" if delivery.code != "000000" else "000001"

    with pytest.raises(EmailLinkFlowError) as rejected:
        await service.confirm(
            ConfirmEmailLinkRequest(code=invalid_code),
            current,
            CONTEXT,
        )

    assert rejected.value.code == "EMAIL_LINK_INVALID"
    assert await db_session.get(PasswordCredential, current.user.id) is None
    code_token = await db_session.scalar(
        select(AuthActionToken).where(
            AuthActionToken.challenge_id == delivery.challenge_id,
            AuthActionToken.token_kind == "code",
        )
    )
    assert code_token.failed_attempts == 1
    assert code_token.consumed_at is None


@pytest.mark.asyncio
async def test_existing_password_account_cannot_start_another_email_binding(
    db_session,
):
    current = await create_github_session(db_session)
    current.user.password_credential = PasswordCredential(
        password_hash=PasswordService().hash_password(PASSWORD),
        password_changed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    await db_session.commit()
    service = EmailLinkService(
        db_session,
        PasswordService(),
        clock=lambda: NOW,
    )

    with pytest.raises(EmailLinkFlowError) as rejected:
        await service.start(start_payload(), current, CONTEXT)

    assert rejected.value.code == "EMAIL_LOGIN_ALREADY_ENABLED"
    await db_session.rollback()
    assert await db_session.scalar(select(AuthActionToken)) is None
