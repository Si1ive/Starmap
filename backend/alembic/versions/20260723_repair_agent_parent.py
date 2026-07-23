"""repair missing agent run parent column

Revision ID: 20260723_repair_agent_parent
Revises: 20260723_agent_thread_events
Create Date: 2026-07-23

This is a forward-only repair for databases whose Alembic version was advanced
while ``agent_runs.parent_run_id`` was absent. Fresh databases already receive
the column from ``20260723_agent_timeline``, so this migration is a no-op there.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "20260723_repair_agent_parent"
down_revision: Union[str, Sequence[str], None] = "20260723_agent_thread_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("agent_runs")}

    if "parent_run_id" not in columns:
        op.add_column(
            "agent_runs",
            sa.Column("parent_run_id", mysql.VARCHAR(32), nullable=True),
        )

    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("agent_runs")}
    if "idx_agent_run_parent" not in indexes:
        op.create_index(
            "idx_agent_run_parent",
            "agent_runs",
            ["parent_run_id"],
        )

    foreign_keys = {
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys("agent_runs")
    }
    if "fk_agent_run_parent" not in foreign_keys:
        op.create_foreign_key(
            "fk_agent_run_parent",
            "agent_runs",
            "agent_runs",
            ["parent_run_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    # The repaired objects belong to 20260723_agent_timeline. Removing them
    # here would make the schema invalid for the migration we downgrade to.
    pass
