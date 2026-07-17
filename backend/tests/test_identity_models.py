import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects import mysql, sqlite

from app.db.types import UUIDBinary
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


def test_identity_domain_registers_all_core_tables():
    expected = {
        "users",
        "user_profiles",
        "auth_identities",
        "password_credentials",
        "auth_sessions",
        "auth_action_tokens",
        "auth_events",
        "user_consents",
    }

    assert {
        model.__table__.name
        for model in (
            User,
            UserProfile,
            AuthIdentity,
            PasswordCredential,
            AuthSession,
            AuthActionToken,
            AuthEvent,
            UserConsent,
        )
    } == expected


def test_user_email_and_external_identity_constraints_are_explicit():
    user_constraints = {
        constraint.name
        for constraint in inspect(User).local_table.constraints
    }
    identity_constraints = {
        constraint.name
        for constraint in inspect(AuthIdentity).local_table.constraints
    }

    assert "uq_users_email_normalized" in user_constraints
    assert "uq_identity_provider_subject" in identity_constraints
    assert "uq_identity_user_provider" in identity_constraints


def test_session_and_action_tokens_only_expose_digest_columns():
    assert "token" not in AuthSession.__table__.columns
    assert "csrf_secret" not in AuthSession.__table__.columns
    assert AuthSession.__table__.columns.token_hash.type.length == 32
    assert AuthSession.__table__.columns.csrf_secret_hash.type.length == 32

    assert "token" not in AuthActionToken.__table__.columns
    assert AuthActionToken.__table__.columns.token_hash.type.length == 32


def test_uuid_binary_round_trip_and_rejects_wrong_length():
    column_type = UUIDBinary()
    value = uuid.uuid4()

    encoded = column_type.process_bind_param(value, sqlite.dialect())
    assert encoded == value.bytes
    assert column_type.process_result_value(encoded, sqlite.dialect()) == value
    assert column_type.process_bind_param(str(value), mysql.dialect()) == value.bytes

    with pytest.raises(ValueError):
        column_type.process_bind_param(b"short", sqlite.dialect())


def test_identity_timestamps_use_mysql_microsecond_precision():
    compiled = User.__table__.columns.created_at.type.compile(dialect=mysql.dialect())

    assert compiled == "DATETIME(6)"
