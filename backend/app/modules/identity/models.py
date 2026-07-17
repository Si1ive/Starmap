"""Persistence models for learning-user authentication and account ownership."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.mysql import Base
from app.db.types import UUIDBinary, new_uuid7


def utc_now() -> datetime:
    """Return a naive UTC datetime for MySQL ``DATETIME(6)`` columns."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


UNSIGNED_INTEGER = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
UNSIGNED_SMALL_INTEGER = SmallInteger().with_variant(
    mysql.SMALLINT(unsigned=True),
    "mysql",
)
UNSIGNED_BIG_INTEGER = BigInteger().with_variant(
    mysql.BIGINT(unsigned=True),
    "mysql",
)
UTC_DATETIME = DateTime(timezone=False).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)
TOKEN_DIGEST = LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
IP_ADDRESS = LargeBinary(16).with_variant(mysql.VARBINARY(16), "mysql")


class User(Base):
    """Stable learning-user account and lifecycle state."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary(),
        primary_key=True,
        default=new_uuid7,
    )
    email_normalized: Mapped[Optional[str]] = mapped_column(String(320))
    email_display: Mapped[Optional[str]] = mapped_column(String(320))
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(UTC_DATETIME)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending_email",
    )
    auth_version: Mapped[int] = mapped_column(
        UNSIGNED_INTEGER,
        nullable=False,
        default=1,
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UTC_DATETIME)
    last_login_method: Mapped[Optional[str]] = mapped_column(String(32))
    activated_at: Mapped[Optional[datetime]] = mapped_column(UTC_DATETIME)
    suspended_at: Mapped[Optional[datetime]] = mapped_column(UTC_DATETIME)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(UTC_DATETIME)
    created_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    row_version: Mapped[int] = mapped_column(
        UNSIGNED_INTEGER,
        nullable=False,
        default=1,
    )

    profile: Mapped[Optional["UserProfile"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    password_credential: Mapped[Optional["PasswordCredential"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    identities: Mapped[list["AuthIdentity"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "email_normalized",
            name="uq_users_email_normalized",
        ),
        Index("idx_users_status_created", "status", "created_at"),
        Index("idx_users_deleted", "deleted_at"),
        {"comment": "学习用户稳定账户主体"},
    )


class UserProfile(Base):
    """Mutable, non-sensitive user presentation fields."""

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    avatar_object_key: Mapped[Optional[str]] = mapped_column(String(512))
    avatar_source: Mapped[Optional[str]] = mapped_column(String(24))
    locale: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="zh-CN",
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Asia/Shanghai",
    )
    created_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    user: Mapped[User] = relationship(back_populates="profile")

    __table_args__ = ({"comment": "学习用户基础资料"},)


class AuthIdentity(Base):
    """External login identity linked to an internal user."""

    __tablename__ = "auth_identities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary(),
        primary_key=True,
        default=new_uuid7,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(191), nullable=False)
    provider_username: Mapped[Optional[str]] = mapped_column(String(191))
    provider_email: Mapped[Optional[str]] = mapped_column(String(320))
    provider_email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    linked_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UTC_DATETIME)
    updated_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    user: Mapped[User] = relationship(back_populates="identities")

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_identity_provider_subject",
        ),
        UniqueConstraint(
            "user_id",
            "provider",
            name="uq_identity_user_provider",
        ),
        Index("idx_identity_user", "user_id"),
        {"comment": "用户外部登录身份"},
    )


class PasswordCredential(Base):
    """Argon2id password credential kept separate from the user profile."""

    __tablename__ = "password_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    hash_scheme: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="argon2id",
    )
    password_changed_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
    )
    must_change: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    compromised_at: Mapped[Optional[datetime]] = mapped_column(UTC_DATETIME)
    created_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    user: Mapped[User] = relationship(back_populates="password_credential")

    __table_args__ = ({"comment": "学习用户密码凭据"},)


class AuthSession(Base):
    """Revocable opaque browser session."""

    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary(),
        primary_key=True,
        default=new_uuid7,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(TOKEN_DIGEST, nullable=False)
    csrf_secret_hash: Mapped[bytes] = mapped_column(
        TOKEN_DIGEST,
        nullable=False,
    )
    auth_version: Mapped[int] = mapped_column(
        UNSIGNED_INTEGER,
        nullable=False,
    )
    auth_method: Mapped[str] = mapped_column(String(32), nullable=False)
    created_ip: Mapped[Optional[bytes]] = mapped_column(IP_ADDRESS)
    last_ip: Mapped[Optional[bytes]] = mapped_column(IP_ADDRESS)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512))
    device_label: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
    )
    idle_expires_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(UTC_DATETIME)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_session_token_hash"),
        Index(
            "idx_session_user_active",
            "user_id",
            "revoked_at",
            "absolute_expires_at",
        ),
        Index("idx_session_expiry", "absolute_expires_at"),
        Index("idx_session_last_seen", "last_seen_at"),
        {"comment": "学习用户服务端登录会话"},
    )


class AuthActionToken(Base):
    """Single-use email verification, reset, and account action token."""

    __tablename__ = "auth_action_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary(),
        primary_key=True,
        default=new_uuid7,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary(),
        nullable=False,
    )
    token_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(TOKEN_DIGEST, nullable=False)
    key_version: Mapped[int] = mapped_column(
        UNSIGNED_SMALL_INTEGER,
        nullable=False,
    )
    target_value: Mapped[Optional[str]] = mapped_column(String(320))
    request_ip: Mapped[Optional[bytes]] = mapped_column(IP_ADDRESS)
    failed_attempts: Mapped[int] = mapped_column(
        UNSIGNED_SMALL_INTEGER,
        nullable=False,
        default=0,
    )
    max_attempts: Mapped[Optional[int]] = mapped_column(
        UNSIGNED_SMALL_INTEGER,
    )
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
    )
    expires_at: Mapped[datetime] = mapped_column(UTC_DATETIME, nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(UTC_DATETIME)
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(UTC_DATETIME)

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_action_token_hash"),
        Index(
            "idx_action_challenge",
            "challenge_id",
            "token_kind",
        ),
        Index(
            "idx_action_user_purpose",
            "user_id",
            "purpose",
            "created_at",
        ),
        Index(
            "idx_action_cleanup",
            "expires_at",
            "consumed_at",
            "invalidated_at",
        ),
        {"comment": "认证一次性动作令牌"},
    )


class AuthEvent(Base):
    """Append-only authentication security event."""

    __tablename__ = "auth_events"

    id: Mapped[int] = mapped_column(
        UNSIGNED_BIG_INTEGER,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDBinary(),
        ForeignKey("auth_sessions.id", ondelete="SET NULL"),
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(32))
    reason_code: Mapped[Optional[str]] = mapped_column(String(64))
    identifier_hmac: Mapped[Optional[bytes]] = mapped_column(TOKEN_DIGEST)
    ip_address: Mapped[Optional[bytes]] = mapped_column(IP_ADDRESS)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512))
    request_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
    )

    __table_args__ = (
        Index("idx_auth_event_user_time", "user_id", "created_at"),
        Index(
            "idx_auth_event_identifier_time",
            "identifier_hmac",
            "created_at",
        ),
        Index("idx_auth_event_type_time", "event_type", "created_at"),
        Index("idx_auth_event_cleanup", "created_at"),
        {"comment": "认证安全审计事件"},
    )


class UserConsent(Base):
    """Immutable acceptance of a terms or privacy document version."""

    __tablename__ = "user_consents"

    id: Mapped[int] = mapped_column(
        UNSIGNED_BIG_INTEGER,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    document_version: Mapped[str] = mapped_column(String(32), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        UTC_DATETIME,
        nullable=False,
        default=utc_now,
    )
    ip_address: Mapped[Optional[bytes]] = mapped_column(IP_ADDRESS)
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "document_type",
            "document_version",
            name="uq_consent_version",
        ),
        Index("idx_consent_user", "user_id", "accepted_at"),
        {"comment": "用户条款与隐私版本接受记录"},
    )
