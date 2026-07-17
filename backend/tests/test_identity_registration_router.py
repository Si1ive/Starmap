"""HTTP contract tests for public registration endpoints."""

import uuid

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.logging import clear_request_id, set_request_id
from app.middleware.error_handler import APIException, api_exception_handler
from app.modules.identity.anti_bot import AntiBotDecision, get_anti_bot_verifier
from app.modules.identity.email import get_email_sender
from app.modules.identity.rate_limit import (
    RateLimitExceeded,
    get_auth_rate_limiter,
)
from app.modules.identity.registration import (
    EmailVerificationOutcome,
    RegistrationOutcome,
    VerificationDelivery,
)
from app.modules.identity.router import (
    get_registration_service,
    router,
)


class StubRegistrationService:
    def __init__(self):
        self.delivery = VerificationDelivery(
            recipient="Learner@example.com",
            challenge_id=uuid.UUID("01981b38-2700-7000-8000-000000000001"),
            transaction_token="registration-transaction-secret",
            link_token="email-verification-link-secret",
            code="123456",
        )

    async def register(self, payload, context):
        return RegistrationOutcome(
            registration_token=self.delivery.transaction_token,
            delivery=self.delivery,
        )

    async def resend(self, registration_token, context):
        return RegistrationOutcome(
            registration_token=self.delivery.transaction_token,
            delivery=self.delivery,
        )

    async def confirm_email(self, payload, registration_token, context):
        return EmailVerificationOutcome(
            user_id=uuid.UUID("01981b38-2700-7000-8000-000000000002"),
            email="Learner@example.com",
            display_name="测试学习者",
            same_browser=True,
        )


class AllowAntiBot:
    async def verify(self, token, *, action, remote_ip):
        return AntiBotDecision(allowed=True)


class RecordingRateLimiter:
    def __init__(self):
        self.calls = []

    async def enforce(self, action, buckets):
        self.calls.append((action, list(buckets)))


class BlockingRateLimiter:
    async def enforce(self, action, buckets):
        raise RateLimitExceeded(action, "ip", 37)


class RecordingEmailSender:
    def __init__(self):
        self.messages = []

    async def enqueue(self, message):
        self.messages.append(message)


def build_client(*, rate_limiter=None):
    app = FastAPI()
    app.add_exception_handler(APIException, api_exception_handler)
    app.include_router(router, prefix="/api/v1")
    service = StubRegistrationService()
    limiter = rate_limiter or RecordingRateLimiter()
    sender = RecordingEmailSender()
    app.dependency_overrides[get_registration_service] = lambda: service
    app.dependency_overrides[get_auth_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_anti_bot_verifier] = lambda: AllowAntiBot()
    app.dependency_overrides[get_email_sender] = lambda: sender
    return TestClient(app), service, limiter, sender


def registration_body():
    return {
        "display_name": "测试学习者",
        "email": "Learner@Example.com",
        "password": "correct horse battery staple",
        "password_confirmation": "correct horse battery staple",
        "accept_terms": True,
        "accept_privacy": True,
    }


def test_register_returns_generic_body_secure_cookie_and_queues_email():
    client, service, limiter, sender = build_client()

    response = client.post("/api/v1/auth/register", json=registration_body())

    assert response.status_code == 202
    assert response.json()["data"] == {
        "verification_required": True,
        "resend_after_seconds": 60,
    }
    assert service.delivery.link_token not in response.text
    assert service.delivery.code not in response.text
    assert service.delivery.recipient not in response.text
    cookie = response.headers["set-cookie"]
    assert f"{settings.AUTH_REGISTRATION_COOKIE_NAME}=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"

    assert len(sender.messages) == 1
    message = sender.messages[0]
    assert message.recipient == service.delivery.recipient
    assert message.variables["code"] == service.delivery.code
    assert service.delivery.link_token in message.variables["verification_url"]
    action, buckets = limiter.calls[0]
    assert action == "register"
    assert {bucket.dimension for bucket in buckets} == {"ip", "email"}
    assert (
        next(bucket for bucket in buckets if bucket.dimension == "email").value
        == "learner@example.com"
    )


def test_registration_rate_limit_exposes_retry_after_without_running_service():
    client, _, _, sender = build_client(rate_limiter=BlockingRateLimiter())

    response = client.post("/api/v1/auth/register", json=registration_body())

    assert response.status_code == 429
    assert response.json()["code"] == "AUTH_RATE_LIMITED"
    assert response.headers["retry-after"] == "37"
    assert sender.messages == []


def test_api_error_handler_reuses_the_active_request_id():
    app = FastAPI()
    app.add_exception_handler(APIException, api_exception_handler)

    @app.get("/failure")
    async def failure(request: Request):
        set_request_id("request-contract-id")
        raise APIException(
            message="受控错误",
            status_code=400,
            code="CONTROLLED_ERROR",
        )

    try:
        response = TestClient(app).get("/failure")
    finally:
        clear_request_id()

    assert response.headers["x-request-id"] == "request-contract-id"
    assert response.json()["request_id"] == "request-contract-id"


def test_email_confirmation_clears_registration_cookie_and_returns_user():
    client, service, _, _ = build_client()
    client.cookies.set(
        settings.AUTH_REGISTRATION_COOKIE_NAME,
        service.delivery.transaction_token,
    )

    response = client.post(
        "/api/v1/auth/email-verification/confirm",
        json={"code": service.delivery.code},
    )

    assert response.status_code == 200
    assert response.json()["data"]["authenticated"] is False
    assert response.json()["data"]["user"]["email_verified"] is True
    assert response.headers["cache-control"] == "no-store"
    assert "Max-Age=0" in response.headers["set-cookie"]
