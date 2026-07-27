"""support thread memory deletion tasks

Revision ID: 20260727_thread_memory_delete
Revises: 20260727_preference_candidates
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "20260727_thread_memory_delete"
down_revision: Union[str, Sequence[str], None] = "20260727_preference_candidates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "agent_memory_update_outbox",
        "run_id",
        existing_type=mysql.VARCHAR(32),
        nullable=True,
    )
    op.add_column(
        "agent_memory_update_outbox",
        sa.Column("task_key", mysql.VARCHAR(128), nullable=True),
    )
    op.create_unique_constraint(
        "uk_agent_memory_outbox_task_key",
        "agent_memory_update_outbox",
        ["task_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uk_agent_memory_outbox_task_key",
        "agent_memory_update_outbox",
        type_="unique",
    )
    op.execute("DELETE FROM agent_memory_update_outbox WHERE run_id IS NULL")
    op.drop_column("agent_memory_update_outbox", "task_key")
    op.alter_column(
        "agent_memory_update_outbox",
        "run_id",
        existing_type=mysql.VARCHAR(32),
        nullable=False,
    )
