"""add correlated retrieval trace fields to vector recall logs

Revision ID: 20260728_vector_recall_trace
Revises: 20260727_memory_trace
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260728_vector_recall_trace"
down_revision: Union[str, Sequence[str], None] = "20260727_memory_trace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name, column_type in (
        ("trace_id", mysql.VARCHAR(64)), ("run_id", mysql.VARCHAR(32)),
        ("activity_id", mysql.VARCHAR(64)), ("attempt_id", mysql.VARCHAR(64)),
        ("phase", mysql.VARCHAR(32)), ("collection_name", mysql.VARCHAR(120)),
        ("query_kind", mysql.VARCHAR(32)), ("raw_query_text", mysql.TEXT()),
    ):
        op.add_column("vector_recall_logs", sa.Column(name, column_type, nullable=True))
    op.create_index("idx_vec_recall_trace", "vector_recall_logs", ["trace_id", "created_at"])
    op.create_index("idx_vec_recall_run", "vector_recall_logs", ["run_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_vec_recall_run", table_name="vector_recall_logs")
    op.drop_index("idx_vec_recall_trace", table_name="vector_recall_logs")
    for name in ("raw_query_text", "query_kind", "collection_name", "phase", "attempt_id", "activity_id", "run_id", "trace_id"):
        op.drop_column("vector_recall_logs", name)
