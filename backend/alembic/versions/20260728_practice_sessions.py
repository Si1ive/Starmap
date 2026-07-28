"""add user-bound mock exam and study timer facts

Revision ID: 20260728_practice_sessions
Revises: 20260728_user_private_corpus
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from app.db.types import UUIDBinary

revision: str = "20260728_practice_sessions"
down_revision: Union[str, Sequence[str], None] = "20260728_user_private_corpus"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "practice_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", UUIDBinary(), nullable=False),
        sa.Column("source_document_id", sa.String(32), nullable=True),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False),
        sa.Column("awarded_score", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["documents.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "idx_practice_sessions_user_created",
        "practice_sessions",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_practice_sessions_user_status", "practice_sessions", ["user_id", "status"]
    )
    op.create_table(
        "practice_session_questions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(32), nullable=False),
        sa.Column("question_id", sa.String(32), nullable=False),
        sa.Column("order_no", sa.Integer(), nullable=False),
        sa.Column("max_score", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["practice_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "session_id", "question_id", name="uk_practice_session_question"
        ),
        sa.UniqueConstraint("session_id", "order_no", name="uk_practice_session_order"),
    )
    op.create_table(
        "practice_answers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(32), nullable=False),
        sa.Column("question_id", sa.String(32), nullable=False),
        sa.Column("user_answer", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("awarded_score", sa.Integer(), nullable=True),
        sa.Column("time_spent_seconds", sa.Integer(), nullable=False),
        sa.Column("saved_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["practice_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("session_id", "question_id", name="uk_practice_answer"),
    )
    op.create_index(
        "idx_practice_answers_question", "practice_answers", ["question_id"]
    )
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
        "idx_study_timer_user_started", "study_timer_records", ["user_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_study_timer_user_started", table_name="study_timer_records")
    op.drop_table("study_timer_records")
    op.drop_index("idx_practice_answers_question", table_name="practice_answers")
    op.drop_table("practice_answers")
    op.drop_table("practice_session_questions")
    op.drop_index("idx_practice_sessions_user_status", table_name="practice_sessions")
    op.drop_index("idx_practice_sessions_user_created", table_name="practice_sessions")
    op.drop_table("practice_sessions")
