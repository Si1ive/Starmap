"""correlate Agent LLM calls with model invocation and run

Revision ID: 20260728_agent_llm_audit
Revises: 20260728_vector_recall_trace
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260728_agent_llm_audit"
down_revision: Union[str, Sequence[str], None] = "20260728_vector_recall_trace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("llm_call_logs", sa.Column("trace_id", mysql.VARCHAR(64), nullable=True))
    op.add_column("llm_call_logs", sa.Column("run_id", mysql.VARCHAR(32), nullable=True))
    op.create_index("idx_llm_calls_trace", "llm_call_logs", ["trace_id", "created_at"])
    op.create_index("idx_llm_calls_run", "llm_call_logs", ["run_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_llm_calls_run", table_name="llm_call_logs")
    op.drop_index("idx_llm_calls_trace", table_name="llm_call_logs")
    op.drop_column("llm_call_logs", "run_id")
    op.drop_column("llm_call_logs", "trace_id")
