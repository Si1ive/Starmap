"""add agent thread events

Revision ID: 20260723_agent_thread_events
Revises: 20260723_agent_timeline
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "20260723_agent_thread_events"
down_revision: Union[str, Sequence[str], None] = "20260723_agent_timeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_thread_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "timeline.item.created",
                "message.started",
                "message.delta",
                "message.completed",
                "message.failed",
                "workflow.updated",
                "workflow.step.updated",
                "workflow.input.required",
                "workflow.approval.required",
                "workflow.artifact.created",
                "workflow.completed",
                "workflow.failed",
                "workflow.cancelled",
                name="agent_thread_event_type",
            ),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["agent_threads.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "thread_id", "sequence", name="uk_agent_thread_event_sequence"
        ),
        sa.Index("idx_agent_thread_event_thread", "thread_id", "sequence"),
        comment="Agent thread 实时事件表",
    )


def downgrade() -> None:
    op.drop_table("agent_thread_events")
