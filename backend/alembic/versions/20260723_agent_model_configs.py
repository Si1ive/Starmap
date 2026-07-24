"""add agent model configs

Revision ID: 20260723_agent_model_configs
Revises: 20260723_repair_agent_parent
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "20260723_agent_model_configs"
down_revision: Union[str, Sequence[str], None] = "20260723_repair_agent_parent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_model_configs",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("display_name", mysql.VARCHAR(100), nullable=False),
        sa.Column(
            "provider",
            mysql.VARCHAR(50),
            nullable=False,
            server_default="openai_compatible",
        ),
        sa.Column("base_url", mysql.VARCHAR(500), nullable=False, server_default=""),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("model_name", mysql.VARCHAR(200), nullable=False),
        sa.Column("online", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("selectable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_slot", sa.Integer(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="2000"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("display_name", name="uk_agent_model_display_name"),
        sa.UniqueConstraint("default_slot", name="uk_agent_model_default_slot"),
        sa.Index("idx_agent_model_online_selectable", "online", "selectable"),
        sa.Index("idx_agent_model_default", "is_default"),
        comment="Agent 多模型配置表",
    )
    op.execute(
        sa.text(
            """
            INSERT INTO agent_model_configs (
                id, display_name, provider, base_url, api_key, model_name,
                online, selectable, is_default, default_slot, temperature, max_tokens,
                timeout_seconds
            )
            SELECT
                'legacy_llm',
                '默认问答模型',
                COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(config_value, '$.provider')), 'null'), 'openai_compatible'),
                COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(config_value, '$.base_url')), 'null'), ''),
                COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(config_value, '$.api_key')), 'null'), ''),
                JSON_UNQUOTE(JSON_EXTRACT(config_value, '$.model')),
                TRUE,
                TRUE,
                TRUE,
                1,
                COALESCE(JSON_EXTRACT(config_value, '$.temperature') + 0.0, 0.2),
                COALESCE(JSON_EXTRACT(config_value, '$.max_tokens') + 0, 2000),
                COALESCE(JSON_EXTRACT(config_value, '$.timeout_seconds') + 0, 60)
            FROM system_configs
            WHERE config_key = 'llm'
              AND JSON_UNQUOTE(JSON_EXTRACT(config_value, '$.enabled')) = 'true'
              AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(config_value, '$.model')), '') <> ''
            LIMIT 1
            """
        )
    )


def downgrade() -> None:
    op.drop_table("agent_model_configs")
