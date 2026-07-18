"""Database and provider tests for secure GitHub OAuth login."""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.identity.context import AuthRequestContext
from app.modules.identity.github_oauth import (
    GitHubOAuthClient,
    GitHubOAuthFlowError,
    GitHubOAuthService,
    GitHubProfile,
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
from app.modules.identity.schemas import (
    GitHubOAuthLinkStartRequest,
    GitHubOAuthStartRequest,
)
from app.modules.identity.security import (
    action_token_digest,
    csrf_token_digest,
    derive_csrf_token,
    session_token_digest,
)
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
NOW = datetime(2026, 7, 17, 11, 0, 0)
CONTEXT = AuthRequestContext(
    remote_ip="192.0.2.44",
    user_agent="GitHub OAuth Test Browser",
    request_id="request-github-oauth-test",
)


class StubGitHubProvider:
    def __init__(self, profile: GitHubProfile):
        self.profile = profile
        self.authorization_calls = []
        self.exchange_calls = []

    def ensure_configured(self):
        return None

    def authorization_url(self, state, code_challenge):
        self.authorization_calls.append((state, code_challenge))
        return f"https://github.example/authorize?state={state}"

    async def exchange_profile(self, code, code_verifier):
        self.exchange_calls.append((code, code_verifier))
        return self.profile


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


def github_profile(
    *,
    subject: str = "12345678",
    username: str = "learner",
    display_name: str = "GitHub Learner",
    verified_email: str | None = "Learner@Example.com",
) -> GitHubProfile:
    return GitHubProfile(
        subject=subject,
        username=username,
        display_name=display_name,
        verified_email=verified_email,
    )


def start_payload(**overrides) -> GitHubOAuthStartRequest:
    values = {
        "source": "login",
        "return_path": "/agent/thread-1?focus=question",
        "remember_me": True,
        "accept_terms": True,
        "accept_privacy": True,
    }
    values.update(overrides)
    return GitHubOAuthStartRequest(**values)


async def start_oauth(db_session, provider, **overrides):
    service = GitHubOAuthService(db_session, provider, clock=lambda: NOW)
    outcome = await service.start(start_payload(**overrides), CONTEXT)
    state, code_challenge = provider.authorization_calls[-1]
    return service, outcome, state, code_challenge


async def create_authenticated_user(
    db_session,
    *,
    email: str = "account@example.com",
    session_token: str = "current-session-token-with-enough-entropy",
) -> AuthenticatedSession:
    user = User(
        email_normalized=email,
        email_display=email,
        email_verified_at=NOW,
        status="active",
        activated_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    user.profile = UserProfile(
        display_name="Password Learner",
        created_at=NOW,
        updated_at=NOW,
    )
    csrf_token = derive_csrf_token(session_token)
    session = AuthSession(
        id=uuid.UUID("01981b38-2700-7000-8000-000000000090"),
        token_hash=session_token_digest(session_token),
        csrf_secret_hash=csrf_token_digest(csrf_token),
        auth_version=1,
        auth_method="password",
        device_label="Chrome on macOS",
        created_at=NOW,
        last_seen_at=NOW,
        idle_expires_at=NOW.replace(hour=23),
        absolute_expires_at=NOW.replace(day=24),
    )
    user.sessions.append(session)
    db_session.add(user)
    await db_session.commit()
    return AuthenticatedSession(
        user=user,
        profile=user.profile,
        session=session,
        csrf_token=csrf_token,
    )


@pytest.mark.asyncio
async def test_start_persists_only_state_and_verifier_digests(db_session):
    provider = StubGitHubProvider(github_profile())

    _, outcome, state, code_challenge = await start_oauth(
        db_session,
        provider,
        return_path="https://attacker.example/callback",
    )

    token = await db_session.scalar(select(AuthActionToken))
    assert token.token_hash == action_token_digest(state, "github_oauth_state")
    assert token.metadata_json["return_path"] == "/today"
    assert token.metadata_json["source"] == "login"
    assert state not in str(token.metadata_json)
    assert outcome.verifier_cookie not in str(token.metadata_json)
    assert (
        token.metadata_json["verifier_hash"]
        == action_token_digest(
            outcome.verifier_cookie,
            "github_oauth_state",
        ).hex()
    )
    expected_challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(outcome.verifier_cookie.encode("ascii")).digest()
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    assert code_challenge == expected_challenge


@pytest.mark.asyncio
async def test_authenticated_user_can_bind_github_identity(db_session):
    session_token = "current-session-token-with-enough-entropy"
    current = await create_authenticated_user(
        db_session,
        session_token=session_token,
    )
    provider = StubGitHubProvider(
        github_profile(
            subject="87654321",
            username="linked-learner",
            verified_email="github@example.com",
        )
    )
    service = GitHubOAuthService(db_session, provider, clock=lambda: NOW)
    start = await service.start_link(
        GitHubOAuthLinkStartRequest(return_path="/account"),
        current,
        CONTEXT,
    )
    state, _ = provider.authorization_calls[-1]

    outcome = await service.callback(
        state=state,
        code="github-link-code",
        provider_error=None,
        verifier_cookie=start.verifier_cookie,
        context=CONTEXT,
        previous_session_token=session_token,
    )

    identity = await db_session.scalar(select(AuthIdentity))
    events = (await db_session.scalars(select(AuthEvent))).all()
    assert outcome.linked is True
    assert outcome.login is None
    assert outcome.return_path == "/account"
    assert identity.user_id == current.user.id
    assert identity.provider_subject == "87654321"
    assert identity.provider_username == "linked-learner"
    assert events[-1].event_type == "identity_link"
    assert events[-1].session_id == current.session.id


@pytest.mark.asyncio
async def test_github_link_requires_the_session_that_started_it(db_session):
    current = await create_authenticated_user(db_session)
    provider = StubGitHubProvider(github_profile(subject="87654321"))
    service = GitHubOAuthService(db_session, provider, clock=lambda: NOW)
    start = await service.start_link(
        GitHubOAuthLinkStartRequest(),
        current,
        CONTEXT,
    )
    state, _ = provider.authorization_calls[-1]

    with pytest.raises(GitHubOAuthFlowError) as raised:
        await service.callback(
            state=state,
            code="github-link-code",
            provider_error=None,
            verifier_cookie=start.verifier_cookie,
            context=CONTEXT,
            previous_session_token="different-session-token-with-enough-entropy",
        )

    assert raised.value.code == "GITHUB_LINK_AUTH_REQUIRED"
    assert raised.value.redirect_path == "/account"
    assert await db_session.scalar(select(AuthIdentity)) is None


@pytest.mark.asyncio
async def test_cancelled_github_link_returns_to_account(db_session):
    current = await create_authenticated_user(db_session)
    provider = StubGitHubProvider(github_profile(subject="87654321"))
    service = GitHubOAuthService(db_session, provider, clock=lambda: NOW)
    start = await service.start_link(
        GitHubOAuthLinkStartRequest(),
        current,
        CONTEXT,
    )
    state, _ = provider.authorization_calls[-1]

    with pytest.raises(GitHubOAuthFlowError) as raised:
        await service.callback(
            state=state,
            code=None,
            provider_error="access_denied",
            verifier_cookie=start.verifier_cookie,
            context=CONTEXT,
            previous_session_token="current-session-token-with-enough-entropy",
        )

    assert raised.value.code == "GITHUB_OAUTH_CANCELLED"
    assert raised.value.redirect_path == "/account"
    assert provider.exchange_calls == []


@pytest.mark.asyncio
async def test_new_verified_github_identity_creates_user_and_session(db_session):
    provider = StubGitHubProvider(github_profile())
    service, start, state, _ = await start_oauth(db_session, provider)

    outcome = await service.callback(
        state=state,
        code="github-authorization-code",
        provider_error=None,
        verifier_cookie=start.verifier_cookie,
        context=CONTEXT,
        previous_session_token=None,
    )

    user = await db_session.scalar(select(User))
    identity = await db_session.scalar(select(AuthIdentity))
    consents = (await db_session.scalars(select(UserConsent))).all()
    session = await db_session.scalar(select(AuthSession))
    assert outcome.new_user is True
    assert outcome.return_path == "/onboarding"
    assert user.status == "active"
    assert user.email_normalized == "learner@example.com"
    assert user.email_verified_at == NOW
    assert identity.provider == "github"
    assert identity.provider_subject == "12345678"
    assert identity.provider_username == "learner"
    assert {consent.document_type for consent in consents} == {
        "terms",
        "privacy",
    }
    assert session.auth_method == "github"
    assert outcome.login.cookie_max_age == 30 * 24 * 60 * 60
    assert provider.exchange_calls == [
        ("github-authorization-code", start.verifier_cookie)
    ]


@pytest.mark.asyncio
async def test_existing_stable_identity_logs_in_without_changing_primary_email(
    db_session,
):
    user = User(
        email_normalized="primary@example.com",
        email_display="Primary@example.com",
        email_verified_at=NOW,
        status="active",
        activated_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    user.profile = UserProfile(
        display_name="Existing Learner",
        created_at=NOW,
        updated_at=NOW,
    )
    user.identities.append(
        AuthIdentity(
            provider="github",
            provider_subject="12345678",
            provider_username="old-name",
            provider_email="old-github@example.com",
            provider_email_verified=True,
            linked_at=NOW,
            updated_at=NOW,
        )
    )
    db_session.add(user)
    await db_session.commit()

    provider = StubGitHubProvider(
        github_profile(
            username="renamed-user",
            verified_email="new-github@example.com",
        )
    )
    service, start, state, _ = await start_oauth(
        db_session,
        provider,
        source="login",
        return_path="/today?view=compact",
        accept_terms=False,
        accept_privacy=False,
        remember_me=False,
    )

    outcome = await service.callback(
        state=state,
        code="code-for-existing-user",
        provider_error=None,
        verifier_cookie=start.verifier_cookie,
        context=CONTEXT,
        previous_session_token=None,
    )

    await db_session.refresh(user)
    identity = await db_session.scalar(select(AuthIdentity))
    assert outcome.new_user is False
    assert outcome.return_path == "/today?view=compact"
    assert user.email_normalized == "primary@example.com"
    assert user.email_display == "Primary@example.com"
    assert identity.provider_username == "renamed-user"
    assert identity.provider_email == "new-github@example.com"


@pytest.mark.asyncio
async def test_same_verified_email_never_auto_links_existing_account(db_session):
    existing = User(
        email_normalized="learner@example.com",
        email_display="learner@example.com",
        email_verified_at=NOW,
        status="active",
        activated_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    existing.profile = UserProfile(
        display_name="Password Learner",
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(existing)
    await db_session.commit()
    provider = StubGitHubProvider(github_profile())
    service, start, state, _ = await start_oauth(db_session, provider)

    with pytest.raises(GitHubOAuthFlowError) as raised:
        await service.callback(
            state=state,
            code="conflicting-account-code",
            provider_error=None,
            verifier_cookie=start.verifier_cookie,
            context=CONTEXT,
            previous_session_token=None,
        )

    assert raised.value.code == "GITHUB_ACCOUNT_LINK_REQUIRED"
    assert await db_session.scalar(select(AuthIdentity)) is None
    assert await db_session.scalar(select(AuthSession)) is None
    events = (await db_session.scalars(select(AuthEvent))).all()
    assert events[-1].reason_code == "existing_email_requires_link"


@pytest.mark.asyncio
async def test_new_github_account_requires_current_legal_consents(db_session):
    provider = StubGitHubProvider(github_profile())
    service, start, state, _ = await start_oauth(
        db_session,
        provider,
        source="login",
        accept_terms=False,
        accept_privacy=False,
    )

    with pytest.raises(GitHubOAuthFlowError) as raised:
        await service.callback(
            state=state,
            code="new-account-without-consent",
            provider_error=None,
            verifier_cookie=start.verifier_cookie,
            context=CONTEXT,
            previous_session_token=None,
        )

    assert raised.value.code == "GITHUB_CONSENT_REQUIRED"
    assert await db_session.scalar(select(User)) is None
    assert await db_session.scalar(select(AuthIdentity)) is None
    assert await db_session.scalar(select(AuthSession)) is None


@pytest.mark.asyncio
async def test_missing_verified_email_is_blocked_and_state_is_single_use(db_session):
    provider = StubGitHubProvider(github_profile(verified_email=None))
    service, start, state, _ = await start_oauth(db_session, provider)

    with pytest.raises(GitHubOAuthFlowError) as first:
        await service.callback(
            state=state,
            code="missing-email-code",
            provider_error=None,
            verifier_cookie=start.verifier_cookie,
            context=CONTEXT,
            previous_session_token=None,
        )
    assert first.value.code == "GITHUB_EMAIL_REQUIRED"
    assert await db_session.scalar(select(User)) is None

    with pytest.raises(GitHubOAuthFlowError) as replay:
        await service.callback(
            state=state,
            code="replayed-code",
            provider_error=None,
            verifier_cookie=start.verifier_cookie,
            context=CONTEXT,
            previous_session_token=None,
        )
    assert replay.value.code == "GITHUB_OAUTH_STATE_INVALID"


@pytest.mark.asyncio
async def test_pkce_cookie_mismatch_invalidates_transaction(db_session):
    provider = StubGitHubProvider(github_profile())
    service, start, state, _ = await start_oauth(db_session, provider)

    with pytest.raises(GitHubOAuthFlowError) as mismatch:
        await service.callback(
            state=state,
            code="authorization-code",
            provider_error=None,
            verifier_cookie=f"{start.verifier_cookie}wrong",
            context=CONTEXT,
            previous_session_token=None,
        )
    assert mismatch.value.code == "GITHUB_OAUTH_STATE_INVALID"
    assert provider.exchange_calls == []


@pytest.mark.asyncio
async def test_provider_client_uses_pkce_and_stable_user_id():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/login/oauth/access_token":
            body = (await request.aread()).decode()
            assert "code_verifier=pkce-verifier" in body
            return httpx.Response(200, json={"access_token": "temporary-token"})
        if request.url.path == "/user":
            return httpx.Response(
                200,
                json={"id": 987654321, "login": "mutable-name", "name": "Learner"},
            )
        if request.url.path == "/user/emails":
            return httpx.Response(
                200,
                json=[
                    {
                        "email": "verified@example.com",
                        "primary": True,
                        "verified": True,
                    }
                ],
            )
        raise AssertionError(f"unexpected request: {request.url}")

    transport = httpx.MockTransport(handler)
    client = GitHubOAuthClient(
        client_id="client-id",
        client_secret="client-secret",
        callback_url="https://app.example/api/v1/auth/github/callback",
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
    )

    authorization_url = client.authorization_url("random-state", "challenge")
    query = parse_qs(urlsplit(authorization_url).query)
    assert query["state"] == ["random-state"]
    assert query["code_challenge"] == ["challenge"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["user:email"]

    profile = await client.exchange_profile("authorization-code", "pkce-verifier")

    assert profile.subject == "987654321"
    assert profile.username == "mutable-name"
    assert profile.verified_email == "verified@example.com"
    assert all(
        request.headers.get("authorization") == "Bearer temporary-token"
        for request in requests[1:]
    )
