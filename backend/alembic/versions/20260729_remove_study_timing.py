"""remove manual study timing facts and per-answer elapsed time

Revision ID: 20260729_remove_study_timing
Revises: 20260728_learning_activity
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from app.db.types import UUIDBinary

revision: str = "20260729_remove_study_timing"
down_revision: Union[str, Sequence[str], None] = "20260728_learning_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("practice_answers", "time_spent_seconds")
    op.drop_index("idx_study_timer_user_started", table_name="study_timer_records")
    op.drop_table("study_timer_records")


def downgrade() -> None:
    op.create_table(
        "study_timer_records",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", UUIDBinary(), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("planned_seconds", sa.Integer(), nullable=False),
        sa.Column("actual_seconds", sa.Integer(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_study_timer_user_started",
        "study_timer_records",
        ["user_id", "started_at"],
    )
    op.add_column(
        "practice_answers",
        sa.Column(
            "time_spent_seconds",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("practice_answers", "time_spent_seconds", server_default=None)
