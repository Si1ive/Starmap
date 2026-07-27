"""persist safe Memory Outbox failure summaries

Revision ID: 20260727_memory_outbox_error
Revises: 20260727_thread_memory_delete
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_memory_outbox_error"
down_revision: Union[str, Sequence[str], None] = "20260727_thread_memory_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_memory_update_outbox",
        sa.Column("last_error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_memory_update_outbox", "last_error_message")
