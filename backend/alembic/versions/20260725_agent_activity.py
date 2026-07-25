"""add public workflow activity event

Revision ID: 20260725_agent_activity
Revises: 20260724_agent_unlimited
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_agent_activity"
down_revision: Union[str, Sequence[str], None] = "20260724_agent_unlimited"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_THREAD_EVENT_TYPES = (
    "timeline.item.created", "message.started", "message.delta",
    "message.completed", "message.failed", "workflow.updated",
    "workflow.step.updated", "workflow.input.required",
    "workflow.approval.required", "workflow.artifact.created",
    "workflow.completed", "workflow.failed", "workflow.cancelled",
)
NEW_THREAD_EVENT_TYPES = (*OLD_THREAD_EVENT_TYPES, "workflow.activity.updated")


def _event_enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values)


def upgrade() -> None:
    op.alter_column(
        "agent_thread_events",
        "event_type",
        existing_type=_event_enum(OLD_THREAD_EVENT_TYPES),
        type_=_event_enum(NEW_THREAD_EVENT_TYPES),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM agent_thread_events "
            "WHERE event_type = 'workflow.activity.updated'"
        )
    )
    op.alter_column(
        "agent_thread_events",
        "event_type",
        existing_type=_event_enum(NEW_THREAD_EVENT_TYPES),
        type_=_event_enum(OLD_THREAD_EVENT_TYPES),
        existing_nullable=False,
    )
