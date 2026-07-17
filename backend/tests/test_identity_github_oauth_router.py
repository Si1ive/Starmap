"""HTTP contract tests for the GitHub OAuth browser flow."""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.middleware.error_handler import APIException, api_exception_handler
from app.modules.identity.github_oauth import (
    GitHubOAuthCallbackOutcome,
    GitHubOAuthFlowError,
    GitHubOAuthStartOutcome,
)
from app.modules.identity.rate_limit import get_auth_rate_limiter
from app.modules.identity.router import get_github_oauth_service, router
from app.modules.identity.session import LoginOutcome

TRUSTED_ORIGIN = "http://localhost:5173"
NOW = datetime(2026, 7, 17, 12, 0, 0)
SESSION_TOKEN = "github-session-token-with-enough-entropy"
CSRF_TOKEN = "github-csrf-token-with-enough-entropy"
VERIFIER_COOKIE = "v" * 86


class StubGitHubOAuthService:
    def __init__(self):
        self.start_calls = []
        self.callback_calls = []

    async def start(self, payload, context):
        self.start_calls.append((payload, context))
        return GitHubOAuthStartOutcome(
            authorization_url="https://github.com/login/oauth/authorize?state=secret",
            expires_at=NOW + timedelta(minutes=10),
            verifier_cookie=VERIFIER_COOKIE,
        )

    async def callback(self, **values):
        self.callback_calls.append(values)
        if values["code"] == "conflict":
            raise GitHubOAuthFlowError(
                "GITHUB_ACCOUNT_LINK_REQUIRED",
                "需要先验证现有账号",
                status_code=409,
                return_path="/today?view=compact",
            )
        user = SimpleNamespace(
            id=uuid.UUID("01981b38-2700-7000-8000-000000000081"),
            email_display="learner@example.com",
            email_normalized="learner@example.com",
            email_verified_at=NOW,
        )
        profile = SimpleNamespace(
            display_name="GitHub Learner",
            locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        session = SimpleNamespace(
            id=uuid.UUID("01981b38-2700-7000-8000-000000000082"),
            auth_method="github",
            device_label="Chrome on macOS",
            created_at=NOW,
            idle_expires_at=NOW + timedelta(hours=12),
            absolute_expires_at=NOW + timedelta(days=7),
        )
        return GitHubOAuthCallbackOutcome(
            login=LoginOutcome(
                user=user,
                profile=profile,
                session=session,
                session_token=SESSION_TOKEN,
                csrf_token=CSRF_TOKEN,
                cookie_max_age=None,
            ),
            return_path="/today?view=compact",
            new_user=False,
        )


class RecordingRateLimiter:
    def __init__(self):
        self.calls = []

    async def enforce(self, action, buckets):
        self.calls.append((action, list(buckets)))


def build_client():
    app = FastAPI()
    app.add_exception_handler(APIException, api_exception_handler)
    app.include_router(router, prefix="/api/v1")
    service = StubGitHubOAuthService()
    limiter = RecordingRateLimiter()
    app.dependency_overrides[get_github_oauth_service] = lambda: service
    app.dependency_overrides[get_auth_rate_limiter] = lambda: limiter
    client = TestClient(app, headers={"Origin": TRUSTED_ORIGIN})
    return client, service, limiter


def test_start_requires_trusted_json_and_sets_short_http_only_pkce_cookie():
    client, service, limiter = build_client()

    response = client.post(
        "/api/v1/auth/github/start",
        json={
            "source": "register",
            "return_path": "/agent/thread-1",
            "remember_me": True,
            "accept_terms": True,
            "accept_privacy": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["authorization_url"].startswith(
        "https://github.com/"
    )
    assert VERIFIER_COOKIE not in response.text
    oauth_cookie = next(
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{settings.AUTH_GITHUB_OAUTH_COOKIE_NAME}=")
    )
    assert "HttpOnly" in oauth_cookie
    assert "SameSite=lax" in oauth_cookie
    assert "Max-Age=600" in oauth_cookie
    assert response.headers["cache-control"] == "no-store"
    assert service.start_calls[0][0].source == "register"
    assert limiter.calls[0][0] == "github-oauth-start"

    rejected = client.post(
        "/api/v1/auth/github/start",
        json={"source": "login"},
        headers={"Origin": "https://attacker.example"},
    )
    assert rejected.status_code == 403


def test_callback_rotates_session_and_clears_pkce_cookie():
    client, service, _ = build_client()
    client.cookies.set(settings.AUTH_GITHUB_OAUTH_COOKIE_NAME, VERIFIER_COOKIE)

    response = client.get(
        "/api/v1/auth/github/callback?state=oauth-state&code=success",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "http://localhost:5173/today" "?view=compact&oauth=success&new_user=0"
    )
    cookies = response.headers.get_list("set-cookie")
    assert any(
        value.startswith(f"{settings.AUTH_SESSION_COOKIE_NAME}={SESSION_TOKEN}")
        and "HttpOnly" in value
        for value in cookies
    )
    assert any(
        value.startswith(f"{settings.AUTH_GITHUB_OAUTH_COOKIE_NAME}=")
        and "Max-Age=0" in value
        for value in cookies
    )
    assert service.callback_calls[0]["verifier_cookie"] == VERIFIER_COOKIE
    assert SESSION_TOKEN not in response.text


def test_callback_failure_redirects_with_safe_code_without_session():
    client, _, _ = build_client()
    client.cookies.set(settings.AUTH_GITHUB_OAUTH_COOKIE_NAME, VERIFIER_COOKIE)

    response = client.get(
        "/api/v1/auth/github/callback?state=oauth-state&code=conflict",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith(
        "http://localhost:5173/login?oauth_error=GITHUB_ACCOUNT_LINK_REQUIRED"
    )
    assert settings.AUTH_SESSION_COOKIE_NAME not in response.headers.get(
        "set-cookie", ""
    )
    assert response.headers["cache-control"] == "no-store"
