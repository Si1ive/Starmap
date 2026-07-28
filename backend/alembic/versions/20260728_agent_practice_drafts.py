"""allow Agent runs to create session-native practice drafts

Revision ID: 20260728_agent_practice_drafts
Revises: 20260728_practice_hints
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_agent_practice_drafts"
down_revision: Union[str, Sequence[str], None] = "20260728_practice_hints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _index_names(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        item["name"]
        for item in [
            *inspector.get_indexes(table),
            *inspector.get_unique_constraints(table),
        ]
        if item.get("name")
    }


def _foreign_key_names(table: str) -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_foreign_keys(table)
        if item.get("name")
    }


def upgrade() -> None:
    session_columns = _column_names("practice_sessions")
    if "source_type" not in session_columns:
        op.add_column(
            "practice_sessions",
            sa.Column("source_type", sa.String(24), nullable=False, server_default="document"),
        )
    if "agent_thread_id" not in session_columns:
        op.add_column(
            "practice_sessions", sa.Column("agent_thread_id", sa.String(32), nullable=True)
        )
    if "agent_run_id" not in session_columns:
        op.add_column(
            "practice_sessions", sa.Column("agent_run_id", sa.String(32), nullable=True)
        )
    session_fks = _foreign_key_names("practice_sessions")
    if "fk_practice_sessions_agent_thread" not in session_fks:
        op.create_foreign_key(
            "fk_practice_sessions_agent_thread", "practice_sessions", "agent_threads",
            ["agent_thread_id"], ["id"], ondelete="SET NULL",
        )
    if "fk_practice_sessions_agent_run" not in session_fks:
        op.create_foreign_key(
            "fk_practice_sessions_agent_run", "practice_sessions", "agent_runs",
            ["agent_run_id"], ["id"], ondelete="SET NULL",
        )
    session_indexes = _index_names("practice_sessions")
    if "idx_practice_sessions_agent_thread" not in session_indexes:
        op.create_index(
            "idx_practice_sessions_agent_thread", "practice_sessions",
            ["agent_thread_id", "created_at"],
        )
    if "uk_practice_sessions_agent_run" not in session_indexes:
        op.create_unique_constraint(
            "uk_practice_sessions_agent_run", "practice_sessions", ["agent_run_id"]
        )
    op.alter_column(
        "practice_sessions",
        "started_at",
        existing_type=sa.DateTime(),
        nullable=True,
    )

    item_columns = _column_names("practice_session_questions")
    if "item_id" not in item_columns:
        op.add_column(
            "practice_session_questions", sa.Column("item_id", sa.String(32), nullable=True)
        )
    if "source_type" not in item_columns:
        op.add_column(
            "practice_session_questions",
            sa.Column(
                "source_type", sa.String(24), nullable=False, server_default="question_bank"
            ),
        )
    op.execute("UPDATE practice_session_questions SET item_id = question_id WHERE item_id IS NULL")
    op.alter_column(
        "practice_session_questions",
        "item_id",
        existing_type=sa.String(32),
        nullable=False,
    )
    item_indexes = _index_names("practice_session_questions")
    if "uk_practice_session_item" not in item_indexes:
        op.create_unique_constraint(
            "uk_practice_session_item", "practice_session_questions", ["session_id", "item_id"]
        )
    if "uk_practice_session_question" in item_indexes:
        op.drop_constraint(
            "uk_practice_session_question", "practice_session_questions", type_="unique"
        )
    op.alter_column(
        "practice_session_questions",
        "question_id",
        existing_type=sa.String(32),
        nullable=True,
    )

    if "session_question_id" not in _column_names("practice_answers"):
        op.add_column(
            "practice_answers", sa.Column("session_question_id", sa.Integer(), nullable=True)
        )
    op.execute(
        """
        UPDATE practice_answers pa
        JOIN practice_session_questions psq
          ON psq.session_id = pa.session_id AND psq.question_id = pa.question_id
        SET pa.session_question_id = psq.id
        WHERE pa.session_question_id IS NULL
        """
    )
    op.alter_column(
        "practice_answers",
        "session_question_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    if "fk_practice_answers_session_question" not in _foreign_key_names("practice_answers"):
        op.create_foreign_key(
            "fk_practice_answers_session_question", "practice_answers",
            "practice_session_questions", ["session_question_id"], ["id"],
            ondelete="CASCADE",
        )
    answer_indexes = _index_names("practice_answers")
    # The replacement starts with session_id and must exist before the old
    # unique index is dropped because MySQL also uses it for the session FK.
    if "uk_practice_answer_item" not in answer_indexes:
        op.create_unique_constraint(
            "uk_practice_answer_item", "practice_answers",
            ["session_id", "session_question_id"],
        )
    if "uk_practice_answer" in answer_indexes:
        op.drop_constraint("uk_practice_answer", "practice_answers", type_="unique")
    op.alter_column(
        "practice_answers",
        "question_id",
        existing_type=sa.String(32),
        nullable=True,
    )


def downgrade() -> None:
    # Agent-native rows cannot be represented by the old mandatory question FK.
    op.execute("DELETE FROM practice_sessions WHERE source_type = 'agent'")
    op.alter_column("practice_answers", "question_id", existing_type=sa.String(32), nullable=False)
    op.drop_constraint("uk_practice_answer_item", "practice_answers", type_="unique")
    op.create_unique_constraint(
        "uk_practice_answer", "practice_answers", ["session_id", "question_id"]
    )
    op.drop_constraint(
        "fk_practice_answers_session_question", "practice_answers", type_="foreignkey"
    )
    op.drop_column("practice_answers", "session_question_id")
    op.alter_column(
        "practice_session_questions", "question_id", existing_type=sa.String(32), nullable=False
    )
    op.drop_constraint(
        "uk_practice_session_item", "practice_session_questions", type_="unique"
    )
    op.create_unique_constraint(
        "uk_practice_session_question",
        "practice_session_questions",
        ["session_id", "question_id"],
    )
    op.drop_column("practice_session_questions", "source_type")
    op.drop_column("practice_session_questions", "item_id")
    op.alter_column("practice_sessions", "started_at", existing_type=sa.DateTime(), nullable=False)
    op.drop_constraint("uk_practice_sessions_agent_run", "practice_sessions", type_="unique")
    op.drop_index("idx_practice_sessions_agent_thread", table_name="practice_sessions")
    op.drop_constraint("fk_practice_sessions_agent_run", "practice_sessions", type_="foreignkey")
    op.drop_constraint("fk_practice_sessions_agent_thread", "practice_sessions", type_="foreignkey")
    op.drop_column("practice_sessions", "agent_run_id")
    op.drop_column("practice_sessions", "agent_thread_id")
    op.drop_column("practice_sessions", "source_type")
