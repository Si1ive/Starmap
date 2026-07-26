"""Add foundational Agent memory tables.

Revision ID: 20260726_agent_memory_foundation
Revises: 20260725_agent_activity
Create Date: 2026-07-26 18:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "20260726_agent_memory_foundation"
down_revision: Union[str, Sequence[str], None] = "20260725_agent_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_thread_memory_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active_topic_json", sa.JSON(), nullable=True),
        sa.Column("topic_stack_json", sa.JSON(), nullable=True),
        sa.Column("active_task_json", sa.JSON(), nullable=True),
        sa.Column("referents_json", sa.JSON(), nullable=True),
        sa.Column("latest_understanding_run_id", mysql.VARCHAR(32), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["agent_threads.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["latest_understanding_run_id"], ["agent_runs.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("thread_id", name="uk_agent_thread_memory_thread"),
        sa.Index("idx_agent_thread_memory_user", "user_id"),
        comment="Agent 线程热记忆状态表",
    )

    op.create_table(
        "agent_memory_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=True),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=True),
        sa.Column(
            "memory_scope",
            sa.Enum("thread", "user", "run", name="agent_memory_scope"),
            nullable=False,
        ),
        sa.Column("source_kind", mysql.VARCHAR(50), nullable=False),
        sa.Column("fact_type", mysql.VARCHAR(64), nullable=False),
        sa.Column("idempotency_key", mysql.VARCHAR(128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["agent_threads.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "idempotency_key", name="uk_agent_memory_event_idempotency"
        ),
        sa.Index("idx_agent_memory_event_thread", "thread_id", "created_at"),
        sa.Index("idx_agent_memory_event_user", "user_id", "created_at"),
        comment="Agent 长期记忆事件表",
    )

    op.create_table(
        "agent_memory_snapshots",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("standalone_request", sa.Text(), nullable=True),
        sa.Column("understanding_json", sa.JSON(), nullable=False),
        sa.Column("selection_metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["agent_threads.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("run_id", name="uk_agent_memory_snapshot_run"),
        sa.Index("idx_agent_memory_snapshot_thread", "thread_id", "created_at"),
        sa.Index("idx_agent_memory_snapshot_run", "run_id"),
        comment="Agent 记忆快照表",
    )

    op.create_table(
        "agent_memory_snapshot_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("memory_need", mysql.VARCHAR(64), nullable=False),
        sa.Column("memory_partition", mysql.VARCHAR(64), nullable=False),
        sa.Column("source_kind", mysql.VARCHAR(50), nullable=False),
        sa.Column("source_id", mysql.VARCHAR(64), nullable=True),
        sa.Column("item_key", mysql.VARCHAR(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("selection_reason", mysql.VARCHAR(255), nullable=True),
        sa.Column("dropped_reason", mysql.VARCHAR(255), nullable=True),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["agent_memory_snapshots.id"], ondelete="CASCADE"
        ),
        sa.Index("idx_agent_memory_snapshot_item_snapshot", "snapshot_id"),
        sa.Index(
            "idx_agent_memory_snapshot_item_need",
            "memory_need",
            "memory_partition",
        ),
        comment="Agent 记忆快照项表",
    )

    op.create_table(
        "agent_memory_update_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("event_type", mysql.VARCHAR(64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "processing", "completed", "failed",
                name="agent_memory_outbox_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker_id", mysql.VARCHAR(64), nullable=True),
        sa.Column(
            "scheduled_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.Column("processed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["agent_threads.id"], ondelete="CASCADE"
        ),
        sa.Index("idx_agent_memory_outbox_status", "status", "scheduled_at"),
        sa.Index("idx_agent_memory_outbox_run", "run_id"),
        comment="Agent 记忆更新 Outbox 表",
    )

    op.create_table(
        "user_learning_mastery",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("subject_id", mysql.VARCHAR(64), nullable=True),
        sa.Column("knowledge_point_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("mastery_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("incorrect_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_evidence_id", mysql.VARCHAR(64), nullable=True),
        sa.Column("last_graded_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "knowledge_point_id", name="uk_user_learning_mastery"
        ),
        sa.Index("idx_user_learning_mastery_subject", "subject_id"),
        comment="用户学习掌握度表",
    )

    op.create_table(
        "agent_conversation_summaries",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("start_sequence", sa.BigInteger(), nullable=False),
        sa.Column("end_sequence", sa.BigInteger(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("source_message_ids_json", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("superseded_by_id", mysql.VARCHAR(32), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["agent_threads.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["agent_conversation_summaries.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "thread_id",
            "start_sequence",
            "end_sequence",
            name="uk_agent_conversation_summary_range",
        ),
        sa.Index(
            "idx_agent_conversation_summary_thread",
            "thread_id",
            "end_sequence",
        ),
        comment="Agent 对话摘要表",
    )

    op.create_table(
        "agent_memory_items",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=True),
        sa.Column(
            "scope",
            sa.Enum("user", "thread", name="agent_memory_item_scope"),
            nullable=False,
        ),
        sa.Column("item_type", mysql.VARCHAR(64), nullable=False),
        sa.Column("item_key", mysql.VARCHAR(128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active", "superseded", "deleted",
                name="agent_memory_item_status",
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("source_snapshot_id", mysql.VARCHAR(32), nullable=True),
        sa.Column("last_confirmed_run_id", mysql.VARCHAR(32), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["agent_threads.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["agent_memory_snapshots.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_confirmed_run_id"], ["agent_runs.id"], ondelete="SET NULL"
        ),
        sa.Index("idx_agent_memory_item_scope", "scope", "user_id", "thread_id"),
        sa.Index("idx_agent_memory_item_type", "item_type", "status"),
        comment="Agent 长期记忆项表",
    )


def downgrade() -> None:
    op.drop_table("agent_memory_items")
    op.drop_table("agent_conversation_summaries")
    op.drop_table("user_learning_mastery")
    op.drop_table("agent_memory_update_outbox")
    op.drop_table("agent_memory_snapshot_items")
    op.drop_table("agent_memory_snapshots")
    op.drop_table("agent_memory_events")
    op.drop_table("agent_thread_memory_states")
