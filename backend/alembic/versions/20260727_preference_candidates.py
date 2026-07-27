"""add governed agent preference candidates

Revision ID: 20260727_preference_candidates
Revises: 20260726_memory_outbox_unique
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "20260727_preference_candidates"
down_revision: Union[str, Sequence[str], None] = "20260726_memory_outbox_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_preference_candidates",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=True),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=True),
        sa.Column("scope", sa.Enum("user", "thread"), nullable=False),
        sa.Column("source_kind", mysql.VARCHAR(64), nullable=False),
        sa.Column("source_id", mysql.VARCHAR(64), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("preference_key", mysql.VARCHAR(64), nullable=False),
        sa.Column("preference_value_json", mysql.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "invalidated"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("extractor_version", mysql.VARCHAR(64), nullable=False),
        sa.Column("model_name", mysql.VARCHAR(200), nullable=False),
        sa.Column("model_config_id", mysql.VARCHAR(32), nullable=True),
        sa.Column("decided_by", mysql.VARCHAR(32), nullable=True),
        sa.Column("decision_reason", mysql.VARCHAR(255), nullable=True),
        sa.Column("decided_at", mysql.DATETIME(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(), nullable=False),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["agent_threads.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_kind",
            "source_id",
            "preference_key",
            name="uk_agent_preference_candidate_source_key",
        ),
        comment="Agent 用户偏好候选表",
    )
    op.create_index(
        "idx_agent_preference_candidate_user_status",
        "agent_preference_candidates",
        ["user_id", "status", "preference_key"],
    )
    op.create_index(
        "idx_agent_preference_candidate_thread",
        "agent_preference_candidates",
        ["thread_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_agent_preference_candidate_thread",
        table_name="agent_preference_candidates",
    )
    op.drop_index(
        "idx_agent_preference_candidate_user_status",
        table_name="agent_preference_candidates",
    )
    op.drop_table("agent_preference_candidates")
