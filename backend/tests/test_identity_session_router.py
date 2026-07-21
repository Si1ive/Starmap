"""HTTP contract tests for password login and current-session endpoints."""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.middleware.error_handler import APIException, api_exception_handler
from app.modules.identity.dependencies import get_session_service
from app.modules.identity.email import get_email_sender
from app.modules.identity.email_link import EmailLinkDelivery, EmailLinkOutcome
from app.modules.identity.rate_limit import get_auth_rate_limiter
from app.modules.identity.router import (
    get_email_link_service,
    get_login_service,
    router,
)
from app.modules.identity.security import csrf_token_digest
from app.modules.identity.session import (
    AuthenticatedSession,
    LoginFlowError,
    LoginOutcome,
    SessionManagementError,
    SessionSummary,
)

TRUSTED_ORIGIN = "http://localhost:5173"
NOW = datetime(2026, 7, 17, 10, 0, 0)
SESSION_TOKEN = "browser-session-token-with-enough-entropy"
CSRF_TOKEN = "browser-csrf-token-with-enough-entropy"


class StubLoginService:
    def __init__(self, current):
        self.current = current
        self.calls = []

    async def login(self, payload, context, previous_session_token):
        self.calls.append((payload, context, previous_session_token))
        if payload.email == "denied@example.com":
            raise LoginFlowError(
                "AUTH_INVALID_CREDENTIALS",
                "邮箱或密码错误",
                status_code=401,
            )
        return LoginOutcome(
            user=self.current.user,
            profile=self.current.profile,
            session=self.current.session,
            session_token=SESSION_TOKEN,
            csrf_token=CSRF_TOKEN,
            cookie_max_age=(30 * 24 * 60 * 60 if payload.remember_me else None),
        )


class StubSessionService:
    def __init__(self, current):
        self.current = current
        self.authenticate_calls = []
        self.logout_calls = []
        self.list_calls = []
        self.revoke_calls = []

    async def authenticate(self, raw_token, context):
        self.authenticate_calls.append((raw_token, context))
        if raw_token != SESSION_TOKEN:
            return None
        return self.current

    async def logout(self, current, context):
        self.logout_calls.append((current, context))

    async def list_active_sessions(self, current):
        self.list_calls.append(current)
        return [
            SessionSummary(
                id=current.session.id,
                auth_method=current.session.auth_method,
                device_label=current.session.device_label,
                created_at=current.session.created_at,
                last_seen_at=current.session.last_seen_at,
                idle_expires_at=current.session.idle_expires_at,
                absolute_expires_at=current.session.absolute_expires_at,
                is_current=True,
                location_label=None,
            ),
            SessionSummary(
                id=uuid.UUID("01981b38-2700-7000-8000-000000000023"),
                auth_method="github",
                device_label="Safari on iPhone",
                created_at=NOW - timedelta(days=1),
                last_seen_at=NOW - timedelta(minutes=5),
                idle_expires_at=NOW + timedelta(hours=4),
                absolute_expires_at=NOW + timedelta(days=6),
                is_current=False,
                location_label="本地网络",
            ),
        ]

    async def revoke_other_session(self, current, session_id, context):
        self.revoke_calls.append((current, session_id, context))
        if session_id == current.session.id:
            raise SessionManagementError(
                "CURRENT_SESSION_LOGOUT_REQUIRED",
                "当前会话请使用退出登录",
                status_code=409,
            )


class RecordingRateLimiter:
    def __init__(self):
        self.calls = []

    async def enforce(self, action, buckets):
        self.calls.append((action, list(buckets)))


class StubEmailLinkService:
    def __init__(self):
        self.calls = []
        self.delivery = EmailLinkDelivery(
            recipient="Bound.Email@example.com",
            challenge_id=uuid.UUID("01981b38-2700-7000-8000-000000000024"),
            link_token="email-link-secret-with-enough-entropy",
            code="654321",
        )

    async def start(self, payload, current, context):
        self.calls.append(("start", payload, current, context))
        return self.delivery

    async def confirm(self, payload, current, context):
        self.calls.append(("confirm", payload, current, context))
        return EmailLinkOutcome(email=self.delivery.recipient)


class RecordingEmailSender:
    def __init__(self):
        self.messages = []

    async def enqueue(self, message):
        self.messages.append(message)


def current_session():
    user = SimpleNamespace(
        id=uuid.UUID("01981b38-2700-7000-8000-000000000021"),
        email_display="Learner@example.com",
        email_normalized="learner@example.com",
        email_verified_at=NOW,
        password_credential=SimpleNamespace(),
    )
    profile = SimpleNamespace(
        display_name="测试学习者",
        locale="zh-CN",
        timezone="Asia/Shanghai",
    )
    session = SimpleNamespace(
        id=uuid.UUID("01981b38-2700-7000-8000-000000000022"),
        auth_method="password",
        device_label="Chrome on macOS",
        created_at=NOW,
        last_seen_at=NOW,
        idle_expires_at=NOW + timedelta(hours=12),
        absolute_expires_at=NOW + timedelta(days=7),
        csrf_secret_hash=csrf_token_digest(CSRF_TOKEN),
    )
    return AuthenticatedSession(
        user=user,
        profile=profile,
        session=session,
        csrf_token=CSRF_TOKEN,
    )


def build_client():
    app = FastAPI()
    app.add_exception_handler(APIException, api_exception_handler)
    app.include_router(router, prefix="/api/v1")
    current = current_session()
    login_service = StubLoginService(current)
    session_service = StubSessionService(current)
    limiter = RecordingRateLimiter()
    app.dependency_overrides[get_login_service] = lambda: login_service
    app.dependency_overrides[get_session_service] = lambda: session_service
    app.dependency_overrides[get_auth_rate_limiter] = lambda: limiter
    client = TestClient(app, headers={"Origin": TRUSTED_ORIGIN})
    return client, login_service, session_service, limiter


def build_email_link_client():
    app = FastAPI()
    app.add_exception_handler(APIException, api_exception_handler)
    app.include_router(router, prefix="/api/v1")
    current = current_session()
    current.user.password_credential = None
    current.session.auth_method = "github"
    session_service = StubSessionService(current)
    email_link_service = StubEmailLinkService()
    limiter = RecordingRateLimiter()
    sender = RecordingEmailSender()
    app.dependency_overrides[get_session_service] = lambda: session_service
    app.dependency_overrides[get_email_link_service] = lambda: email_link_service
    app.dependency_overrides[get_auth_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_email_sender] = lambda: sender
    client = TestClient(app, headers={"Origin": TRUSTED_ORIGIN})
    client.cookies.set(settings.AUTH_SESSION_COOKIE_NAME, SESSION_TOKEN)
    return client, email_link_service, limiter, sender


def login_body(**overrides):
    body = {
        "email": "Learner@Example.com",
        "password": "correct horse battery staple",
        "remember_me": False,
    }
    body.update(overrides)
    return body


def test_login_sets_http_only_cookie_without_exposing_session_token():
    client, login_service, _, limiter = build_client()

    response = client.post("/api/v1/auth/login", json=login_body())

    assert response.status_code == 200
    assert response.json()["data"]["authenticated"] is True
    assert response.json()["data"]["csrf_token"] == CSRF_TOKEN
    assert response.json()["data"]["user"]["id"]
    assert SESSION_TOKEN not in response.text
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(
        value
        for value in cookies
        if value.startswith(f"{settings.AUTH_SESSION_COOKIE_NAME}=")
    )
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert "Path=/" in session_cookie
    assert "Max-Age" not in session_cookie
    assert response.headers["cache-control"] == "no-store"
    assert login_service.calls[0][2] is None

    action, buckets = limiter.calls[0]
    assert action == "login"
    assert {bucket.dimension for bucket in buckets} == {
        "ip",
        "identifier",
        "device",
    }


def test_remembered_login_sets_persistent_cookie_and_rotates_existing_cookie():
    client, login_service, _, _ = build_client()
    client.cookies.set(settings.AUTH_SESSION_COOKIE_NAME, "old-session-token")

    response = client.post(
        "/api/v1/auth/login",
        json=login_body(remember_me=True),
    )

    assert response.status_code == 200
    session_cookie = next(
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{settings.AUTH_SESSION_COOKIE_NAME}=")
    )
    assert f"Max-Age={30 * 24 * 60 * 60}" in session_cookie
    assert login_service.calls[0][2] == "old-session-token"


def test_login_failure_keeps_generic_shape_and_does_not_set_session_cookie():
    client, _, _, _ = build_client()

    response = client.post(
        "/api/v1/auth/login",
        json=login_body(email="denied@example.com"),
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    assert response.json()["message"] == "邮箱或密码错误"
    assert settings.AUTH_SESSION_COOKIE_NAME not in response.headers.get(
        "set-cookie", ""
    )
    assert response.headers["cache-control"] == "no-store"


def test_me_requires_server_session_and_returns_current_user():
    client, _, session_service, _ = build_client()

    unauthorized = client.get("/api/v1/auth/me")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["code"] == "AUTHENTICATION_REQUIRED"

    client.cookies.set(settings.AUTH_SESSION_COOKIE_NAME, SESSION_TOKEN)
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["data"]["user"]["email"] == "Learner@example.com"
    assert response.json()["data"]["user"]["email_login_enabled"] is True
    assert response.json()["data"]["csrf_token"] == CSRF_TOKEN
    assert response.headers["cache-control"] == "no-store"
    assert session_service.authenticate_calls[-1][0] == SESSION_TOKEN


def test_me_does_not_treat_a_github_contact_email_as_email_login():
    client, _, session_service, _ = build_client()
    session_service.current.user.password_credential = None
    session_service.current.session.auth_method = "github"
    client.cookies.set(settings.AUTH_SESSION_COOKIE_NAME, SESSION_TOKEN)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["data"]["user"]["email"] == "Learner@example.com"
    assert response.json()["data"]["user"]["email_verified"] is True
    assert response.json()["data"]["user"]["email_login_enabled"] is False


def test_email_link_start_requires_csrf_and_only_sends_secrets_by_email():
    client, service, limiter, sender = build_email_link_client()
    body = {
        "email": "Bound.Email@Example.com",
        "password": "correct horse battery staple",
        "password_confirmation": "correct horse battery staple",
    }

    missing_csrf = client.post("/api/v1/auth/email-link/start", json=body)
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_INVALID"
    assert service.calls == []
    assert sender.messages == []

    response = client.post(
        "/api/v1/auth/email-link/start",
        json=body,
        headers={"X-CSRF-Token": CSRF_TOKEN},
    )

    assert response.status_code == 202
    assert response.json()["data"] == {
        "verification_required": True,
        "resend_after_seconds": 60,
    }
    assert service.delivery.code not in response.text
    assert service.delivery.link_token not in response.text
    assert len(sender.messages) == 1
    message = sender.messages[0]
    assert message.template_id == "link-email"
    assert message.recipient == service.delivery.recipient
    assert message.variables["code"] == service.delivery.code
    assert service.delivery.link_token in message.variables["verification_url"]
    assert limiter.calls[0][0] == "email-link-start"
    assert {bucket.dimension for bucket in limiter.calls[0][1]} == {
        "user",
        "email",
        "ip",
    }
    assert response_has_no_store(response)


def test_email_link_confirm_requires_csrf_and_reports_verified_binding():
    client, service, limiter, _ = build_email_link_client()

    response = client.post(
        "/api/v1/auth/email-link/confirm",
        json={"code": service.delivery.code},
        headers={"X-CSRF-Token": CSRF_TOKEN},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "linked": True,
        "email": service.delivery.recipient,
    }
    assert service.calls[0][0] == "confirm"
    assert service.calls[0][1].code == service.delivery.code
    assert limiter.calls[0][0] == "email-link-confirm"
    assert response_has_no_store(response)


def test_logout_rejects_untrusted_origin_before_session_lookup():
    client, _, session_service, _ = build_client()
    client.cookies.set(settings.AUTH_SESSION_COOKIE_NAME, SESSION_TOKEN)

    response = client.post(
        "/api/v1/auth/logout",
        json={},
        headers={
            "Origin": "https://attacker.example",
            "X-CSRF-Token": CSRF_TOKEN,
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_ORIGIN_INVALID"
    assert session_service.authenticate_calls == []
    assert session_service.logout_calls == []


def test_logout_requires_csrf_and_revokes_the_current_session():
    client, _, session_service, _ = build_client()
    client.cookies.set(settings.AUTH_SESSION_COOKIE_NAME, SESSION_TOKEN)

    missing_csrf = client.post("/api/v1/auth/logout", json={})
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_INVALID"
    assert session_service.logout_calls == []

    response = client.post(
        "/api/v1/auth/logout",
        json={},
        headers={"X-CSRF-Token": CSRF_TOKEN},
    )

    assert response.status_code == 200
    assert response.json()["data"]["authenticated"] is False
    assert len(session_service.logout_calls) == 1
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"


def test_session_list_requires_login_and_returns_only_safe_summaries():
    client, _, session_service, _ = build_client()

    unauthorized = client.get("/api/v1/auth/sessions")
    assert unauthorized.status_code == 401
    assert session_service.list_calls == []

    client.cookies.set(settings.AUTH_SESSION_COOKIE_NAME, SESSION_TOKEN)
    response = client.get("/api/v1/auth/sessions")

    assert response.status_code == 200
    sessions = response.json()["data"]["sessions"]
    assert [item["is_current"] for item in sessions] == [True, False]
    assert sessions[1]["location_label"] == "本地网络"
    assert sessions[1]["last_seen_at"].endswith("Z")
    assert {
        "token",
        "token_hash",
        "csrf_token",
        "csrf_secret_hash",
        "user_agent",
        "last_ip",
    }.isdisjoint(sessions[0])
    assert session_service.list_calls == [session_service.current]
    assert response.headers["cache-control"] == "no-store"


def test_revoke_other_session_requires_csrf_and_reports_current_session_conflict():
    client, _, session_service, _ = build_client()
    client.cookies.set(settings.AUTH_SESSION_COOKIE_NAME, SESSION_TOKEN)
    other_session_id = "01981b38-2700-7000-8000-000000000023"

    missing_csrf = client.post(
        f"/api/v1/auth/sessions/{other_session_id}/revoke",
        json={},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_INVALID"
    assert session_service.revoke_calls == []

    revoked = client.post(
        f"/api/v1/auth/sessions/{other_session_id}/revoke",
        json={},
        headers={"X-CSRF-Token": CSRF_TOKEN},
    )
    assert revoked.status_code == 200
    assert revoked.json()["data"] == {
        "revoked": True,
        "session_id": other_session_id,
    }
    assert len(session_service.revoke_calls) == 1
    assert response_has_no_store(revoked)

    current_session_id = str(session_service.current.session.id)
    conflict = client.post(
        f"/api/v1/auth/sessions/{current_session_id}/revoke",
        json={},
        headers={"X-CSRF-Token": CSRF_TOKEN},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "CURRENT_SESSION_LOGOUT_REQUIRED"
    assert response_has_no_store(conflict)


def response_has_no_store(response):
    return response.headers["cache-control"] == "no-store"
