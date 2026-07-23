"""add agent conversation messages and thread timeline

Revision ID: 20260723_agent_timeline
Revises: 20260723_add_agent_tables
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "20260723_agent_timeline"
down_revision: Union[str, Sequence[str], None] = "20260723_add_agent_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_threads",
        sa.Column("last_item_sequence", sa.BigInteger(), nullable=False, server_default="0"),
    )

    op.create_table(
        "agent_messages",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=True),
        sa.Column("role", sa.Enum("user", "assistant", "system", name="agent_message_role"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "streaming", "completed", "failed", name="agent_message_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_blocks_json", sa.JSON(), nullable=True),
        sa.Column("client_message_id", mysql.VARCHAR(128), nullable=True),
        sa.Column("error_code", mysql.VARCHAR(64), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.Column("completed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("user_id", "client_message_id", name="uk_agent_message_client_id"),
        sa.Index("idx_agent_message_thread", "thread_id", "created_at"),
        sa.Index("idx_agent_message_run", "run_id"),
        comment="Agent 对话消息表",
    )

    op.create_table(
        "agent_thread_items",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "item_type",
            sa.Enum("message", "workflow", "notice", name="agent_thread_item_type"),
            nullable=False,
        ),
        sa.Column("ref_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=True),
        sa.Column(
            "visibility",
            sa.Enum("visible", "hidden", name="agent_thread_item_visibility"),
            nullable=False,
            server_default="visible",
        ),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("thread_id", "sequence", name="uk_agent_thread_item_sequence"),
        sa.Index("idx_agent_thread_item_thread", "thread_id", "sequence"),
        sa.Index("idx_agent_thread_item_run", "run_id"),
        comment="Agent 线程时间线投影表",
    )

    op.add_column("agent_runs", sa.Column("workflow_key", mysql.VARCHAR(50), nullable=True))
    op.add_column("agent_runs", sa.Column("workflow_version", mysql.VARCHAR(20), nullable=True))
    op.add_column("agent_runs", sa.Column("trigger_message_id", mysql.VARCHAR(32), nullable=True))
    op.add_column("agent_runs", sa.Column("parent_run_id", mysql.VARCHAR(32), nullable=True))
    op.add_column("agent_runs", sa.Column("root_run_id", mysql.VARCHAR(32), nullable=True))
    op.add_column("agent_runs", sa.Column("retry_of_run_id", mysql.VARCHAR(32), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column(
            "presentation",
            sa.Enum("silent", "compact", "workflow", name="agent_run_presentation"),
            nullable=False,
            server_default="workflow",
        ),
    )
    op.add_column("agent_runs", sa.Column("public_title", mysql.VARCHAR(255), nullable=True))
    op.add_column("agent_runs", sa.Column("public_summary", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("current_public_step", mysql.VARCHAR(100), nullable=True))
    op.add_column("agent_runs", sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=True))
    op.add_column("agent_runs", sa.Column("completed_at", mysql.DATETIME(fsp=6), nullable=True))

    op.create_foreign_key(
        "fk_agent_run_trigger_message",
        "agent_runs",
        "agent_messages",
        ["trigger_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for name, column in (
        ("fk_agent_run_parent", "parent_run_id"),
        ("fk_agent_run_root", "root_run_id"),
        ("fk_agent_run_retry", "retry_of_run_id"),
    ):
        op.create_foreign_key(name, "agent_runs", "agent_runs", [column], ["id"], ondelete="SET NULL")

    op.create_index("idx_agent_run_trigger_message", "agent_runs", ["trigger_message_id"])
    op.create_index("idx_agent_run_parent", "agent_runs", ["parent_run_id"])
    op.create_index("idx_agent_run_root", "agent_runs", ["root_run_id"])

    old_event_type = sa.Enum(
        "run.created", "run.status_changed", "run.completed",
        "step.started", "step.completed", "step.failed",
        "tool.called", "tool.result", "message.delta", "message.completed",
        "artifact.rendered", "error", name="agent_event_type",
    )
    new_event_type = sa.Enum(
        "run.created", "run.status_changed", "run.completed", "run.failed",
        "step.started", "step.completed", "step.failed",
        "tool.called", "tool.result", "message.delta", "message.completed",
        "artifact.rendered", "error", name="agent_event_type",
    )
    op.alter_column("agent_events", "event_type", existing_type=old_event_type, type_=new_event_type, nullable=False)


def downgrade() -> None:
    old_event_type = sa.Enum(
        "run.created", "run.status_changed", "run.completed",
        "step.started", "step.completed", "step.failed",
        "tool.called", "tool.result", "message.delta", "message.completed",
        "artifact.rendered", "error", name="agent_event_type",
    )
    new_event_type = sa.Enum(
        "run.created", "run.status_changed", "run.completed", "run.failed",
        "step.started", "step.completed", "step.failed",
        "tool.called", "tool.result", "message.delta", "message.completed",
        "artifact.rendered", "error", name="agent_event_type",
    )
    op.alter_column("agent_events", "event_type", existing_type=new_event_type, type_=old_event_type, nullable=False)

    op.drop_index("idx_agent_run_root", table_name="agent_runs")
    op.drop_index("idx_agent_run_parent", table_name="agent_runs")
    op.drop_index("idx_agent_run_trigger_message", table_name="agent_runs")
    op.drop_constraint("fk_agent_run_retry", "agent_runs", type_="foreignkey")
    op.drop_constraint("fk_agent_run_root", "agent_runs", type_="foreignkey")
    op.drop_constraint("fk_agent_run_parent", "agent_runs", type_="foreignkey")
    op.drop_constraint("fk_agent_run_trigger_message", "agent_runs", type_="foreignkey")

    for column in (
        "completed_at", "started_at", "current_public_step", "public_summary",
        "public_title", "presentation", "retry_of_run_id", "root_run_id",
        "parent_run_id", "trigger_message_id", "workflow_version", "workflow_key",
    ):
        op.drop_column("agent_runs", column)

    op.drop_table("agent_thread_items")
    op.drop_table("agent_messages")
    op.drop_column("agent_threads", "last_item_sequence")
