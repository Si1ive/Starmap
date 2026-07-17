"""建立学习用户身份域核心数据表。

Revision ID: 20260716_user_identity
Revises: 20260714_entity_reextract
Create Date: 2026-07-16 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "20260716_user_identity"
down_revision: Union[str, Sequence[str], None] = "20260714_entity_reextract"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", mysql.BINARY(16), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=True),
        sa.Column("email_display", sa.String(length=320), nullable=True),
        sa.Column("email_verified_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "auth_version",
            mysql.INTEGER(unsigned=True),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("last_login_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("last_login_method", sa.String(length=32), nullable=True),
        sa.Column("activated_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("suspended_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("deleted_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "row_version",
            mysql.INTEGER(unsigned=True),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "email_normalized",
            name="uq_users_email_normalized",
        ),
        comment="学习用户稳定账户主体",
    )
    op.create_index(
        "idx_users_status_created",
        "users",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_users_deleted",
        "users",
        ["deleted_at"],
        unique=False,
    )

    op.create_table(
        "user_profiles",
        sa.Column("user_id", mysql.BINARY(16), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("avatar_object_key", sa.String(length=512), nullable=True),
        sa.Column("avatar_source", sa.String(length=24), nullable=True),
        sa.Column(
            "locale",
            sa.String(length=16),
            server_default=sa.text("'zh-CN'"),
            nullable=False,
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'Asia/Shanghai'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id"),
        comment="学习用户基础资料",
    )

    op.create_table(
        "auth_identities",
        sa.Column("id", mysql.BINARY(16), nullable=False),
        sa.Column("user_id", mysql.BINARY(16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_subject", sa.String(length=191), nullable=False),
        sa.Column("provider_username", sa.String(length=191), nullable=True),
        sa.Column("provider_email", sa.String(length=320), nullable=True),
        sa.Column(
            "provider_email_verified",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "linked_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("last_login_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_identity_provider_subject",
        ),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            name="uq_identity_user_provider",
        ),
        comment="用户外部登录身份",
    )
    op.create_index(
        "idx_identity_user",
        "auth_identities",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "password_credentials",
        sa.Column("user_id", mysql.BINARY(16), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "hash_scheme",
            sa.String(length=32),
            server_default=sa.text("'argon2id'"),
            nullable=False,
        ),
        sa.Column(
            "password_changed_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "must_change",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("compromised_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id"),
        comment="学习用户密码凭据",
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", mysql.BINARY(16), nullable=False),
        sa.Column("user_id", mysql.BINARY(16), nullable=False),
        sa.Column("token_hash", mysql.BINARY(32), nullable=False),
        sa.Column("csrf_secret_hash", mysql.BINARY(32), nullable=False),
        sa.Column(
            "auth_version",
            mysql.INTEGER(unsigned=True),
            nullable=False,
        ),
        sa.Column("auth_method", sa.String(length=32), nullable=False),
        sa.Column("created_ip", mysql.VARBINARY(16), nullable=True),
        sa.Column("last_ip", mysql.VARBINARY(16), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("device_label", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("idle_expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("absolute_expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("revoke_reason", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_session_token_hash"),
        comment="学习用户服务端登录会话",
    )
    op.create_index(
        "idx_session_user_active",
        "auth_sessions",
        ["user_id", "revoked_at", "absolute_expires_at"],
        unique=False,
    )
    op.create_index(
        "idx_session_expiry",
        "auth_sessions",
        ["absolute_expires_at"],
        unique=False,
    )
    op.create_index(
        "idx_session_last_seen",
        "auth_sessions",
        ["last_seen_at"],
        unique=False,
    )

    op.create_table(
        "auth_action_tokens",
        sa.Column("id", mysql.BINARY(16), nullable=False),
        sa.Column("user_id", mysql.BINARY(16), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("challenge_id", mysql.BINARY(16), nullable=False),
        sa.Column("token_kind", sa.String(length=16), nullable=False),
        sa.Column("token_hash", mysql.BINARY(32), nullable=False),
        sa.Column(
            "key_version",
            mysql.SMALLINT(unsigned=True),
            nullable=False,
        ),
        sa.Column("target_value", sa.String(length=320), nullable=True),
        sa.Column("request_ip", mysql.VARBINARY(16), nullable=True),
        sa.Column(
            "failed_attempts",
            mysql.SMALLINT(unsigned=True),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            mysql.SMALLINT(unsigned=True),
            nullable=True,
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("consumed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("invalidated_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_action_token_hash"),
        comment="认证一次性动作令牌",
    )
    op.create_index(
        "idx_action_challenge",
        "auth_action_tokens",
        ["challenge_id", "token_kind"],
        unique=False,
    )
    op.create_index(
        "idx_action_user_purpose",
        "auth_action_tokens",
        ["user_id", "purpose", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_action_cleanup",
        "auth_action_tokens",
        ["expires_at", "consumed_at", "invalidated_at"],
        unique=False,
    )

    op.create_table(
        "auth_events",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("user_id", mysql.BINARY(16), nullable=True),
        sa.Column("session_id", mysql.BINARY(16), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("identifier_hmac", mysql.BINARY(32), nullable=True),
        sa.Column("ip_address", mysql.VARBINARY(16), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["auth_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="认证安全审计事件",
    )
    op.create_index(
        "idx_auth_event_user_time",
        "auth_events",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_auth_event_identifier_time",
        "auth_events",
        ["identifier_hmac", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_auth_event_type_time",
        "auth_events",
        ["event_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_auth_event_cleanup",
        "auth_events",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "user_consents",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("user_id", mysql.BINARY(16), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("document_version", sa.String(length=32), nullable=False),
        sa.Column(
            "accepted_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column("ip_address", mysql.VARBINARY(16), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "document_type",
            "document_version",
            name="uq_consent_version",
        ),
        comment="用户条款与隐私版本接受记录",
    )
    op.create_index(
        "idx_consent_user",
        "user_consents",
        ["user_id", "accepted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_consent_user", table_name="user_consents")
    op.drop_table("user_consents")

    op.drop_index("idx_auth_event_cleanup", table_name="auth_events")
    op.drop_index("idx_auth_event_type_time", table_name="auth_events")
    op.drop_index(
        "idx_auth_event_identifier_time",
        table_name="auth_events",
    )
    op.drop_index("idx_auth_event_user_time", table_name="auth_events")
    op.drop_table("auth_events")

    op.drop_index("idx_action_cleanup", table_name="auth_action_tokens")
    op.drop_index(
        "idx_action_user_purpose",
        table_name="auth_action_tokens",
    )
    op.drop_index(
        "idx_action_challenge",
        table_name="auth_action_tokens",
    )
    op.drop_table("auth_action_tokens")

    op.drop_index("idx_session_last_seen", table_name="auth_sessions")
    op.drop_index("idx_session_expiry", table_name="auth_sessions")
    op.drop_index("idx_session_user_active", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_table("password_credentials")
    op.drop_index("idx_identity_user", table_name="auth_identities")
    op.drop_table("auth_identities")
    op.drop_table("user_profiles")
    op.drop_index("idx_users_deleted", table_name="users")
    op.drop_index("idx_users_status_created", table_name="users")
    op.drop_table("users")
