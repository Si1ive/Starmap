import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.db import get_db
from app.main import app
from app.modules.operations.security import (
    ACCESS_TOKEN_TYPE,
    DEVELOPMENT_JWT_SECRET,
    create_admin_access_token,
    decode_admin_access_token,
    hash_admin_password,
    validate_admin_security_config,
    verify_admin_password,
)


def _password_hash(password: str) -> str:
    iterations = 260_000
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _AuthSession:
    def __init__(self, user):
        self.user = user
        self.added = []
        self.commit_count = 0

    async def execute(self, _statement):
        return _ScalarResult(self.user)

    async def get(self, _model, record_id):
        return self.user if record_id == self.user.id else None

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commit_count += 1


def test_database_admin_can_login_and_token_protects_admin_routes():
    user = SimpleNamespace(
        id="db-admin-1",
        username="database-admin",
        email="database-admin@example.com",
        password_hash=_password_hash("correct-password"),
        role="super_admin",
        permissions=["*"],
        is_active=True,
        last_login_at=None,
        last_login_ip=None,
        created_at=datetime(2026, 7, 14),
        updated_at=datetime(2026, 7, 14),
    )
    session = _AuthSession(user)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        login_response = client.post(
            "/api/v1/admin/auth/login",
            json={
                "username": "database-admin",
                "password": "correct-password",
            },
        )
        assert login_response.status_code == 200
        login_payload = login_response.json()
        assert login_payload["code"] == 200
        token = login_payload["data"]["token"]
        assert token

        me_response = client.get(
            "/api/v1/admin/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_response.status_code == 200
        assert me_response.json()["data"]["id"] == user.id

        anonymous_response = client.get("/api/v1/admin/dashboard/stats")
        assert anonymous_response.status_code == 401
        anonymous_memory_response = client.get(
            "/api/v1/admin/agent-runs/run-private/memory"
        )
        assert anonymous_memory_response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_admin_password_hash_round_trip_and_rejects_bad_inputs():
    password_hash = hash_admin_password("correct-password")

    assert verify_admin_password("correct-password", password_hash)
    assert not verify_admin_password("wrong-password", password_hash)
    assert not verify_admin_password("correct-password", "not-a-password-hash")
    assert not verify_admin_password("correct-password", "pbkdf2_sha256$bad$value")


def test_admin_access_token_round_trip_and_rejects_tampering():
    token = create_admin_access_token("admin-123")

    assert decode_admin_access_token(token) == "admin-123"
    with pytest.raises(ValueError):
        decode_admin_access_token(f"{token}tampered")


def test_admin_access_token_rejects_wrong_token_type():
    token = jwt.encode(
        {
            "sub": "admin-123",
            "type": f"{ACCESS_TOKEN_TYPE}_wrong",
            "iss": settings.ADMIN_JWT_ISSUER,
            "aud": settings.ADMIN_JWT_AUDIENCE,
        },
        settings.ADMIN_JWT_SECRET,
        algorithm=settings.ADMIN_JWT_ALGORITHM,
    )

    with pytest.raises(ValueError):
        decode_admin_access_token(token)


def test_admin_access_token_rejects_expired_token():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "admin-123",
            "type": ACCESS_TOKEN_TYPE,
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
            "iss": settings.ADMIN_JWT_ISSUER,
            "aud": settings.ADMIN_JWT_AUDIENCE,
        },
        settings.ADMIN_JWT_SECRET,
        algorithm=settings.ADMIN_JWT_ALGORITHM,
    )

    with pytest.raises(ValueError):
        decode_admin_access_token(token)


def test_inactive_database_admin_cannot_login():
    user = SimpleNamespace(
        id="inactive-admin",
        username="inactive",
        email="inactive@example.com",
        password_hash=_password_hash("correct-password"),
        role="operator",
        permissions=[],
        is_active=False,
        last_login_at=None,
        last_login_ip=None,
        created_at=datetime(2026, 7, 14),
        updated_at=datetime(2026, 7, 14),
    )
    session = _AuthSession(user)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/admin/auth/login",
            json={"username": "inactive", "password": "correct-password"},
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_production_rejects_default_admin_jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "ADMIN_JWT_SECRET", DEVELOPMENT_JWT_SECRET)

    with pytest.raises(RuntimeError, match="ADMIN_JWT_SECRET"):
        validate_admin_security_config()
