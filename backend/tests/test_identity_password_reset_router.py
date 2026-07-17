"""HTTP contract tests for forgot-password and password-reset endpoints."""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.middleware.error_handler import APIException, api_exception_handler
from app.modules.identity.anti_bot import AntiBotDecision, get_anti_bot_verifier
from app.modules.identity.email import get_email_sender
from app.modules.identity.password_reset import (
    PasswordResetDelivery,
    PasswordResetFlowError,
    PasswordResetOutcome,
    PasswordResetRequestOutcome,
)
from app.modules.identity.rate_limit import get_auth_rate_limiter
from app.modules.identity.router import get_password_reset_service, router

TRUSTED_ORIGIN = "http://localhost:5173"
RESET_TOKEN = "password-reset-token-with-enough-entropy"
CHALLENGE_ID = uuid.UUID("01981b38-2700-7000-8000-000000000041")


class StubPasswordResetService:
    def __init__(self):
        self.request_calls = []
        self.reset_calls = []

    async def request_reset(self, payload, context):
        self.request_calls.append((payload, context))
        if payload.email.casefold() == "learner@example.com":
            return PasswordResetRequestOutcome(
                delivery=PasswordResetDelivery(
                    recipient="Learner@example.com",
                    challenge_id=CHALLENGE_ID,
                    token=RESET_TOKEN,
                )
            )
        return PasswordResetRequestOutcome(delivery=None)

    async def reset_password(self, payload, context):
        self.reset_calls.append((payload, context))
        if payload.token.startswith("invalid"):
            raise PasswordResetFlowError(
                "PASSWORD_RESET_INVALID",
                "重置凭据无效或已过期",
            )
        return PasswordResetOutcome(
            recipient="Learner@example.com",
            challenge_id=CHALLENGE_ID,
        )


class AllowAntiBot:
    def __init__(self):
        self.calls = []

    async def verify(self, token, *, action, remote_ip):
        self.calls.append((token, action, remote_ip))
        return AntiBotDecision(allowed=True)


class RecordingRateLimiter:
    def __init__(self):
        self.calls = []

    async def enforce(self, action, buckets):
        self.calls.append((action, list(buckets)))


class RecordingEmailSender:
    def __init__(self):
        self.messages = []

    async def enqueue(self, message):
        self.messages.append(message)


def build_client():
    app = FastAPI()
    app.add_exception_handler(APIException, api_exception_handler)
    app.include_router(router, prefix="/api/v1")
    service = StubPasswordResetService()
    limiter = RecordingRateLimiter()
    anti_bot = AllowAntiBot()
    sender = RecordingEmailSender()
    app.dependency_overrides[get_password_reset_service] = lambda: service
    app.dependency_overrides[get_auth_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_anti_bot_verifier] = lambda: anti_bot
    app.dependency_overrides[get_email_sender] = lambda: sender
    client = TestClient(app, headers={"Origin": TRUSTED_ORIGIN})
    return client, service, limiter, anti_bot, sender


def reset_body(token=RESET_TOKEN):
    return {
        "token": token,
        "password": "a newly generated password phrase",
        "password_confirmation": "a newly generated password phrase",
    }


def test_forgot_password_keeps_generic_response_and_queues_only_real_delivery():
    client, service, limiter, anti_bot, sender = build_client()

    known = client.post(
        "/api/v1/auth/password/forgot",
        json={"email": "Learner@example.com"},
    )
    unknown = client.post(
        "/api/v1/auth/password/forgot",
        json={"email": "missing@example.com"},
    )

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert known.json()["data"] == {"accepted": True}
    assert RESET_TOKEN not in known.text
    assert "Learner@example.com" not in known.text
    assert known.headers["cache-control"] == "no-store"
    assert known.headers["referrer-policy"] == "no-referrer"
    assert len(service.request_calls) == 2
    assert len(sender.messages) == 1
    message = sender.messages[0]
    assert message.template_id == "reset-password"
    assert message.recipient == "Learner@example.com"
    assert RESET_TOKEN in message.variables["reset_url"]
    assert message.idempotency_key == f"reset-password:{CHALLENGE_ID}"
    action, buckets = limiter.calls[0]
    assert action == "password-forgot"
    assert {bucket.dimension for bucket in buckets} == {"ip", "email"}
    assert anti_bot.calls[0][1] == "password_forgot"


def test_reset_password_clears_session_and_queues_change_notification():
    client, service, limiter, _, sender = build_client()
    client.cookies.set(settings.AUTH_SESSION_COOKIE_NAME, "stale-session")

    response = client.post(
        "/api/v1/auth/password/reset",
        json=reset_body(),
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "password_reset": True,
        "authenticated": False,
    }
    assert RESET_TOKEN not in response.text
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert len(service.reset_calls) == 1
    assert len(sender.messages) == 1
    message = sender.messages[0]
    assert message.template_id == "password-changed"
    assert message.recipient == "Learner@example.com"
    assert message.variables == {}
    action, buckets = limiter.calls[0]
    assert action == "password-reset"
    token_bucket = next(bucket for bucket in buckets if bucket.dimension == "token")
    assert token_bucket.value != RESET_TOKEN


def test_invalid_reset_token_returns_controlled_error_without_notification():
    client, service, _, _, sender = build_client()
    invalid_token = "invalid-password-reset-token-value"

    response = client.post(
        "/api/v1/auth/password/reset",
        json=reset_body(invalid_token),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "PASSWORD_RESET_INVALID"
    assert response.json()["message"] == "重置凭据无效或已过期"
    assert response.headers["cache-control"] == "no-store"
    assert len(service.reset_calls) == 1
    assert sender.messages == []
