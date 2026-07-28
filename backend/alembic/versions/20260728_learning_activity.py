"""add trusted learning activity event facts

Revision ID: 20260728_learning_activity
Revises: 20260728_agent_practice_drafts
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.types import UUIDBinary

revision: str = "20260728_learning_activity"
down_revision: Union[str, Sequence[str], None] = "20260728_agent_practice_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learning_activity_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUIDBinary(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(96), nullable=False),
        sa.Column("thread_id", sa.String(32), nullable=True),
        sa.Column("run_id", sa.String(32), nullable=True),
        sa.Column("topic_keywords_json", sa.JSON(), nullable=False),
        sa.Column("knowledge_point_ids_json", sa.JSON(), nullable=True),
        sa.Column("quality", sa.Float(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_threads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "user_id", "event_type", "source_id", name="uk_learning_activity_source"
        ),
    )
    op.create_index(
        "idx_learning_activity_user_time",
        "learning_activity_events",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "idx_learning_activity_thread",
        "learning_activity_events",
        ["thread_id", "occurred_at"],
    )
    op.create_index(
        "idx_learning_activity_run", "learning_activity_events", ["run_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_learning_activity_run", table_name="learning_activity_events")
    op.drop_index("idx_learning_activity_thread", table_name="learning_activity_events")
    op.drop_index("idx_learning_activity_user_time", table_name="learning_activity_events")
    op.drop_table("learning_activity_events")
