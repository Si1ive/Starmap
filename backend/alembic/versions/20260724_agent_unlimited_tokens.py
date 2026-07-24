"""allow unlimited output tokens for agent models

Revision ID: 20260724_agent_unlimited
Revises: 20260723_agent_model_configs
Create Date: 2026-07-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_agent_unlimited"
down_revision: Union[str, Sequence[str], None] = "20260723_agent_model_configs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "agent_model_configs",
        "max_tokens",
        existing_type=sa.Integer(),
        existing_server_default=sa.text("'2000'"),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE agent_model_configs SET max_tokens = 2000 "
            "WHERE max_tokens IS NULL"
        )
    )
    op.alter_column(
        "agent_model_configs",
        "max_tokens",
        existing_type=sa.Integer(),
        existing_server_default=sa.text("'2000'"),
        nullable=False,
    )
