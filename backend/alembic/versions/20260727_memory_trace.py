"""add immutable before/after memory traces for Agent runs

Revision ID: 20260727_memory_trace
Revises: 20260727_memory_outbox_error
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "20260727_memory_trace"
down_revision: Union[str, Sequence[str], None] = "20260727_memory_outbox_error"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_memory_traces",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("event_sequence", sa.Integer(), nullable=True),
        sa.Column("event_type", mysql.VARCHAR(80), nullable=False),
        sa.Column("changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("before_json", mysql.JSON(), nullable=False),
        sa.Column("after_json", mysql.JSON(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_threads.id"], ondelete="CASCADE"),
        sa.Index("idx_agent_memory_trace_run", "run_id", "id"),
        sa.Index("idx_agent_memory_trace_thread", "thread_id", "created_at"),
        comment="Agent 记忆前后状态观测表",
    )


def downgrade() -> None:
    op.drop_index("idx_agent_memory_trace_thread", table_name="agent_memory_traces")
    op.drop_index("idx_agent_memory_trace_run", table_name="agent_memory_traces")
    op.drop_table("agent_memory_traces")
