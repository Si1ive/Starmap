"""add memory outbox idempotency constraint

Revision ID: 20260726_memory_outbox_unique
Revises: 20260726_agent_memory_foundation
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260726_memory_outbox_unique"
down_revision: Union[str, Sequence[str], None] = "20260726_agent_memory_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 该表此前尚无生产者，增加唯一约束不会遇到历史重复任务；未来同一
    # Run 的同类事实只能有一个异步投影任务，并发重放由数据库兜底。
    op.create_unique_constraint(
        "uk_agent_memory_outbox_run_event",
        "agent_memory_update_outbox",
        ["run_id", "event_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uk_agent_memory_outbox_run_event",
        "agent_memory_update_outbox",
        type_="unique",
    )
