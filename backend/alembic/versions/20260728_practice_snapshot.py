"""freeze question content inside each practice session

Revision ID: 20260728_practice_snapshot
Revises: 20260728_practice_sessions
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_practice_snapshot"
down_revision: Union[str, Sequence[str], None] = "20260728_practice_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "practice_session_questions",
        sa.Column("snapshot_json", sa.JSON(), nullable=True),
    )
    op.execute("""
        UPDATE practice_session_questions psq
        JOIN questions q ON q.id = psq.question_id
        SET psq.snapshot_json = JSON_OBJECT(
            'type', q.type,
            'content', q.content,
            'options', q.options,
            'answer', q.answer,
            'explanation', q.explanation,
            'source', q.source,
            'question_no', q.question_no,
            'chapter_id', COALESCE(q.primary_chapter_id, q.chapter_id),
            'answer_source', q.answer_source,
            'explanation_source', q.explanation_source
        )
        WHERE psq.snapshot_json IS NULL
        """)
    op.alter_column(
        "practice_session_questions",
        "snapshot_json",
        existing_type=sa.JSON(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("practice_session_questions", "snapshot_json")
