"""Database integration tests for password login and opaque sessions."""

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
from app.modules.identity.schemas import LoginRequest
from app.modules.identity.security import (
    PasswordService,
    csrf_token_digest,
    derive_csrf_token,
    session_token_digest,
)
from app.modules.identity.session import (
    LoginFlowError,
    LoginService,
    SessionManagementError,
    SessionService,
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
NOW = datetime(2026, 7, 17, 9, 0, 0)
PASSWORD = "correct horse battery staple"
CONTEXT = AuthRequestContext(
    remote_ip="192.0.2.25",
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
    ),
    request_id="request-login-test",
)


class RecordingRateLimiter:
    def __init__(self, failure_delay: float = 0.0):
        self.failure_delay = failure_delay
        self.failures = []
        self.cleared = []

    async def record_login_failure(self, *, identifier, remote_ip):
        self.failures.append((identifier, remote_ip))
        return self.failure_delay

    async def clear_login_failures(self, *, identifier):
        self.cleared.append(identifier)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
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


async def create_user(
    db_session,
    password_service,
    *,
    email="learner@example.com",
    display_name="测试学习者",
    status="active",
    verified=True,
):
    user = User(
        email_normalized=email.casefold(),
        email_display=email,
        email_verified_at=NOW if verified else None,
        status=status,
        activated_at=NOW if verified else None,
        created_at=NOW,
        updated_at=NOW,
    )
    user.profile = UserProfile(
        display_name=display_name,
        created_at=NOW,
        updated_at=NOW,
    )
    user.password_credential = PasswordCredential(
        password_hash=password_service.hash_password(PASSWORD),
        password_changed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def create_session(
    db_session,
    user,
    *,
    token,
    auth_version=None,
    auth_method="password",
    device_label="Firefox on Linux",
    created_at=NOW - timedelta(hours=2),
    last_seen_at=NOW - timedelta(hours=1),
    idle_expires_at=NOW + timedelta(hours=10),
    absolute_expires_at=NOW + timedelta(days=6),
    revoked_at=None,
):
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=session_token_digest(token),
        csrf_secret_hash=csrf_token_digest(derive_csrf_token(token)),
        auth_version=auth_version if auth_version is not None else user.auth_version,
        auth_method=auth_method,
        device_label=device_label,
        created_at=created_at,
        last_seen_at=last_seen_at,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
        revoked_at=revoked_at,
    )
    db_session.add(auth_session)
    await db_session.commit()
    return auth_session


def login_request(*, password=PASSWORD, remember_me=False):
    return LoginRequest(
        email=" Learner@Example.com ",
        password=password,
        remember_me=remember_me,
    )


@pytest.mark.asyncio
async def test_password_login_persists_only_session_and_csrf_digests(db_session):
    password_service = PasswordService()
    user = await create_user(db_session, password_service)
    limiter = RecordingRateLimiter()
    service = LoginService(
        db_session,
        password_service,
        limiter,
        clock=lambda: NOW,
    )

    outcome = await service.login(login_request(), CONTEXT, None)

    persisted = await db_session.get(AuthSession, outcome.session.id)
    assert persisted.user_id == user.id
    assert persisted.token_hash == session_token_digest(outcome.session_token)
    assert persisted.csrf_secret_hash == csrf_token_digest(outcome.csrf_token)
    assert outcome.csrf_token == derive_csrf_token(outcome.session_token)
    assert outcome.session_token.encode() != persisted.token_hash
    assert outcome.csrf_token.encode() != persisted.csrf_secret_hash
    assert persisted.idle_expires_at == NOW + timedelta(hours=12)
    assert persisted.absolute_expires_at == NOW + timedelta(days=7)
    assert outcome.cookie_max_age is None
    assert persisted.device_label == "Chrome on macOS"
    assert limiter.cleared == ["learner@example.com"]

    refreshed_user = await db_session.get(User, user.id)
    assert refreshed_user.last_login_at == NOW
    assert refreshed_user.last_login_method == "password"
    event = await db_session.scalar(
        select(AuthEvent).where(AuthEvent.event_type == "login")
    )
    assert event.outcome == "success"
    assert event.session_id == persisted.id
    assert event.identifier_hmac is not None


@pytest.mark.asyncio
async def test_email_verification_creates_standard_session(db_session):
    password_service = PasswordService()
    user = await create_user(db_session, password_service)
    previous_token = "previous-session-before-verification"
    previous = AuthSession(
        user_id=user.id,
        token_hash=session_token_digest(previous_token),
        csrf_secret_hash=csrf_token_digest(derive_csrf_token(previous_token)),
        auth_version=user.auth_version,
        auth_method="password",
        created_at=NOW - timedelta(hours=1),
        last_seen_at=NOW - timedelta(hours=1),
        idle_expires_at=NOW + timedelta(hours=11),
        absolute_expires_at=NOW + timedelta(days=6),
    )
    db_session.add(previous)
    await db_session.commit()
    service = SessionService(db_session, clock=lambda: NOW)

    outcome = await service.create_after_email_verification(
        user.id,
        CONTEXT,
        previous_token,
    )

    assert outcome is not None
    assert outcome.user.id == user.id
    assert outcome.profile.display_name == "测试学习者"
    assert outcome.session.auth_method == "email_verification"
    assert outcome.session.idle_expires_at == NOW + timedelta(hours=12)
    assert outcome.session.absolute_expires_at == NOW + timedelta(days=7)
    assert outcome.cookie_max_age is None
    assert outcome.csrf_token == derive_csrf_token(outcome.session_token)

    refreshed_previous = await db_session.get(AuthSession, previous.id)
    assert refreshed_previous.revoked_at == NOW
    assert refreshed_previous.revoke_reason == "email_verification_rotation"
    refreshed_user = await db_session.get(User, user.id)
    assert refreshed_user.last_login_method == "email_verification"
    event = await db_session.scalar(
        select(AuthEvent).where(
            AuthEvent.session_id == outcome.session.id,
            AuthEvent.event_type == "login",
        )
    )
    assert event.provider == "email_verification"
    assert event.reason_code == "same_browser_verification"


@pytest.mark.asyncio
async def test_unknown_and_wrong_password_share_the_same_public_failure(db_session):
    password_service = PasswordService()
    user = await create_user(db_session, password_service)
    limiter = RecordingRateLimiter(failure_delay=0.25)
    observed_sleeps = []

    async def record_sleep(delay):
        observed_sleeps.append(delay)

    service = LoginService(
        db_session,
        password_service,
        limiter,
        clock=lambda: NOW,
        sleeper=record_sleep,
    )

    with pytest.raises(LoginFlowError) as wrong_password:
        await service.login(
            login_request(password="this password is incorrect"),
            CONTEXT,
            None,
        )
    with pytest.raises(LoginFlowError) as unknown_user:
        await service.login(
            LoginRequest(
                email="missing@example.com",
                password=PASSWORD,
            ),
            CONTEXT,
            None,
        )

    assert wrong_password.value.code == unknown_user.value.code
    assert str(wrong_password.value) == str(unknown_user.value)
    assert wrong_password.value.status_code == unknown_user.value.status_code == 401
    assert observed_sleeps == [0.25, 0.25]
    assert len(limiter.failures) == 2
    assert await db_session.scalar(select(AuthSession)) is None
    events = (
        await db_session.scalars(
            select(AuthEvent).where(AuthEvent.event_type == "login")
        )
    ).all()
    assert len(events) == 2
    assert all(event.reason_code == "invalid_credentials" for event in events)
    assert {event.user_id for event in events} == {user.id, None}


@pytest.mark.asyncio
async def test_pending_email_user_is_not_given_an_authenticated_session(db_session):
    password_service = PasswordService()
    user = await create_user(
        db_session,
        password_service,
        status="pending_email",
        verified=False,
    )
    limiter = RecordingRateLimiter()
    service = LoginService(
        db_session,
        password_service,
        limiter,
        clock=lambda: NOW,
    )

    with pytest.raises(LoginFlowError) as pending:
        await service.login(login_request(), CONTEXT, None)

    assert pending.value.code == "EMAIL_VERIFICATION_REQUIRED"
    assert pending.value.status_code == 403
    assert await db_session.scalar(select(AuthSession)) is None
    event = await db_session.scalar(
        select(AuthEvent).where(AuthEvent.user_id == user.id)
    )
    assert event.outcome == "denied"
    assert event.reason_code == "email_verification_required"
    assert limiter.cleared == ["learner@example.com"]


@pytest.mark.asyncio
async def test_remembered_login_rotates_presented_session_and_uses_longer_limits(
    db_session,
):
    password_service = PasswordService()
    user = await create_user(db_session, password_service)
    previous_token = "previous-session-token-with-enough-entropy"
    previous = AuthSession(
        user_id=user.id,
        token_hash=session_token_digest(previous_token),
        csrf_secret_hash=csrf_token_digest(derive_csrf_token(previous_token)),
        auth_version=user.auth_version,
        auth_method="password",
        created_at=NOW - timedelta(hours=1),
        last_seen_at=NOW - timedelta(hours=1),
        idle_expires_at=NOW + timedelta(hours=11),
        absolute_expires_at=NOW + timedelta(days=6),
    )
    db_session.add(previous)
    await db_session.commit()
    service = LoginService(
        db_session,
        password_service,
        RecordingRateLimiter(),
        clock=lambda: NOW,
    )

    outcome = await service.login(
        login_request(remember_me=True),
        CONTEXT,
        previous_token,
    )

    refreshed_previous = await db_session.get(AuthSession, previous.id)
    assert refreshed_previous.revoked_at == NOW
    assert refreshed_previous.revoke_reason == "login_rotation"
    assert outcome.session.idle_expires_at == NOW + timedelta(days=7)
    assert outcome.session.absolute_expires_at == NOW + timedelta(days=30)
    assert outcome.cookie_max_age == 30 * 24 * 60 * 60


@pytest.mark.asyncio
async def test_session_touch_logout_and_auth_version_invalidation(db_session):
    password_service = PasswordService()
    user = await create_user(db_session, password_service)
    current_time = [NOW]
    login_service = LoginService(
        db_session,
        password_service,
        RecordingRateLimiter(),
        clock=lambda: current_time[0],
    )
    outcome = await login_service.login(login_request(), CONTEXT, None)
    session_service = SessionService(
        db_session,
        clock=lambda: current_time[0],
    )

    current_time[0] = NOW + timedelta(minutes=6)
    current = await session_service.authenticate(outcome.session_token, CONTEXT)

    assert current is not None
    assert current.session.last_seen_at == current_time[0]
    assert current.session.idle_expires_at == current_time[0] + timedelta(hours=12)

    await session_service.logout(current, CONTEXT)
    assert await session_service.authenticate(outcome.session_token, CONTEXT) is None
    revoked = await db_session.get(AuthSession, outcome.session.id)
    assert revoked.revoke_reason == "logout"
    logout_event = await db_session.scalar(
        select(AuthEvent).where(AuthEvent.event_type == "logout")
    )
    assert logout_event.session_id == outcome.session.id

    second = await login_service.login(login_request(), CONTEXT, None)
    user.auth_version += 1
    await db_session.commit()

    assert await session_service.authenticate(second.session_token, CONTEXT) is None
    invalidated = await db_session.get(AuthSession, second.session.id)
    assert invalidated.revoke_reason == "auth_version_changed"


@pytest.mark.asyncio
async def test_active_session_list_is_owned_filtered_and_redacted(db_session):
    password_service = PasswordService()
    user = await create_user(db_session, password_service)
    login_service = LoginService(
        db_session,
        password_service,
        RecordingRateLimiter(),
        clock=lambda: NOW,
    )
    login = await login_service.login(login_request(), CONTEXT, None)
    other = await create_session(
        db_session,
        user,
        token="other-active-session-token-with-enough-entropy",
    )
    await create_session(
        db_session,
        user,
        token="expired-session-token-with-enough-entropy",
        idle_expires_at=NOW,
    )
    await create_session(
        db_session,
        user,
        token="revoked-session-token-with-enough-entropy",
        revoked_at=NOW - timedelta(minutes=1),
    )
    await create_session(
        db_session,
        user,
        token="stale-version-session-token-with-enough-entropy",
        auth_version=user.auth_version - 1,
    )
    other_user = await create_user(
        db_session,
        password_service,
        email="other@example.com",
        display_name="其他学习者",
    )
    await create_session(
        db_session,
        other_user,
        token="cross-account-session-token-with-enough-entropy",
    )
    service = SessionService(db_session, clock=lambda: NOW)
    current = await service.authenticate(login.session_token, CONTEXT)

    sessions = await service.list_active_sessions(current)

    assert [item.id for item in sessions] == [login.session.id, other.id]
    assert sessions[0].is_current is True
    assert sessions[1].is_current is False
    assert sessions[1].device_label == "Firefox on Linux"
    assert not hasattr(sessions[0], "token_hash")
    assert not hasattr(sessions[0], "csrf_secret_hash")
    assert not hasattr(sessions[0], "user_agent")
    assert not hasattr(sessions[0], "last_ip")


@pytest.mark.asyncio
async def test_revoke_other_session_enforces_ownership_and_audits(db_session):
    password_service = PasswordService()
    user = await create_user(db_session, password_service)
    login_service = LoginService(
        db_session,
        password_service,
        RecordingRateLimiter(),
        clock=lambda: NOW,
    )
    login = await login_service.login(login_request(), CONTEXT, None)
    target = await create_session(
        db_session,
        user,
        token="revocation-target-token-with-enough-entropy",
        auth_method="github",
    )
    other_user = await create_user(
        db_session,
        password_service,
        email="other@example.com",
        display_name="其他学习者",
    )
    cross_account = await create_session(
        db_session,
        other_user,
        token="cross-account-revoke-token-with-enough-entropy",
    )
    service = SessionService(db_session, clock=lambda: NOW)
    current = await service.authenticate(login.session_token, CONTEXT)

    with pytest.raises(SessionManagementError) as current_session_error:
        await service.revoke_other_session(current, login.session.id, CONTEXT)
    assert current_session_error.value.code == "CURRENT_SESSION_LOGOUT_REQUIRED"
    assert current_session_error.value.status_code == 409

    with pytest.raises(SessionManagementError) as ownership_error:
        await service.revoke_other_session(current, cross_account.id, CONTEXT)
    assert ownership_error.value.code == "SESSION_NOT_FOUND"
    assert ownership_error.value.status_code == 404
    assert (await db_session.get(AuthSession, cross_account.id)).revoked_at is None

    await service.revoke_other_session(current, target.id, CONTEXT)

    revoked = await db_session.get(AuthSession, target.id)
    assert revoked.revoked_at == NOW
    assert revoked.revoke_reason == "user_revoked_other_session"
    event = await db_session.scalar(
        select(AuthEvent).where(
            AuthEvent.event_type == "session_revoked",
            AuthEvent.session_id == target.id,
        )
    )
    assert event is not None
    assert event.user_id == user.id
    assert event.outcome == "success"
    assert event.provider == "github"
    assert event.reason_code == "user_revoked_other_session"
    assert event.request_id == CONTEXT.request_id
