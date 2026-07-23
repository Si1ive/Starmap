"""添加 Agent 对话运行时核心数据表。

Revision ID: 20260723_add_agent_tables
Revises: 20260716_user_identity
Create Date: 2026-07-23 14:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "20260723_add_agent_tables"
down_revision: Union[str, Sequence[str], None] = "20260716_user_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ========================== agent_threads ==========================
    op.create_table(
        "agent_threads",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("title", mysql.VARCHAR(255), nullable=True),
        sa.Column("status", sa.Enum("active", "archived", "deleted", name="agent_thread_status"), nullable=False, server_default="active"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_agent_thread_user", "user_id"),
        sa.Index("idx_agent_thread_status", "status"),
        comment="Agent 线程表：用户对话容器",
    )

    # ========================== agent_runs ==========================
    op.create_table(
        "agent_runs",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("thread_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("user_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("workflow_name", mysql.VARCHAR(50), nullable=False),
        sa.Column("status", sa.Enum("queued", "running", "completed", "failed", "waiting_for_user", "waiting_for_approval", name="agent_run_status"), nullable=False, server_default="queued"),
        sa.Column("input_message", sa.Text(), nullable=True),
        sa.Column("result_artifact_id", mysql.VARCHAR(32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("model_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_model_calls", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("lease_owner", mysql.VARCHAR(64), nullable=True),
        sa.Column("lease_expires_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("client_idempotency_key", mysql.VARCHAR(64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_threads.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "client_idempotency_key", name="uq_agent_run_idempotency"),
        sa.Index("idx_agent_run_thread", "thread_id"),
        sa.Index("idx_agent_run_user", "user_id"),
        sa.Index("idx_agent_run_status", "status"),
        comment="Agent 执行记录表：单次工作流实例",
    )

    # ========================== agent_steps ==========================
    op.create_table(
        "agent_steps",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("parent_step_id", mysql.VARCHAR(32), nullable=True),
        sa.Column("node_name", mysql.VARCHAR(100), nullable=False),
        sa.Column("node_type", sa.Enum("router", "action", "gate", "loop", "render", "wait", name="agent_step_node_type"), nullable=False),
        sa.Column("status", sa.Enum("pending", "running", "completed", "failed", "skipped", name="agent_step_status"), nullable=False, server_default="pending"),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("error_info", sa.JSON(), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("completed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.Index("idx_agent_step_run", "run_id"),
        sa.Index("idx_agent_step_parent", "parent_step_id"),
        comment="Agent 步骤表：工作流节点执行记录",
    )

    # ========================== agent_events ==========================
    op.create_table(
        "agent_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Enum(
            "run.created", "run.status_changed", "run.completed",
            "step.started", "step.completed", "step.failed",
            "tool.called", "tool.result",
            "message.delta", "message.completed",
            "artifact.rendered", "error", name="agent_event_type"
        ), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "sequence", name="uk_agent_event_seq"),
        sa.Index("idx_agent_event_run", "run_id"),
        comment="Agent 事件表：SSE 推送事实源",
    )

    # ========================== agent_run_outbox ==========================
    op.create_table(
        "agent_run_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("status", sa.Enum("pending", "processing", "completed", "failed", name="agent_outbox_status"), nullable=False, server_default="pending"),
        sa.Column("worker_id", mysql.VARCHAR(64), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.Column("processed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.Index("idx_agent_outbox_status", "status", "scheduled_at"),
        sa.Index("idx_agent_outbox_run", "run_id"),
        comment="Agent Outbox 表：任务唤醒队列",
    )

    # ========================== agent_checkpoints ==========================
    op.create_table(
        "agent_checkpoints",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.Index("idx_agent_checkpoint_run", "run_id"),
        comment="Agent 断点表：崩溃恢复用",
    )

    # ========================== agent_loop_turns ==========================
    op.create_table(
        "agent_loop_turns",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("parent_step_id", mysql.VARCHAR(32), nullable=True),
        sa.Column("turn_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("decision_ref", sa.Text(), nullable=True),
        sa.Column("action_key", mysql.VARCHAR(50), nullable=True),
        sa.Column("observation_ref", sa.Text(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "turn_no", name="uk_agent_loop_turn"),
        sa.Index("idx_agent_loop_run", "run_id"),
        comment="Agent Loop 决策表：决策与 observation 持久化",
    )

    # ========================== agent_artifacts ==========================
    op.create_table(
        "agent_artifacts",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("artifact_type", sa.Enum("explanation", "practice", "feedback", "plan", "message", name="agent_artifact_type"), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.Index("idx_agent_artifact_run", "run_id"),
        comment="Agent 产物表：渲染产物",
    )

    # ========================== agent_inputs ==========================
    op.create_table(
        "agent_inputs",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("input_key", mysql.VARCHAR(80), nullable=False),
        sa.Column("input_schema_version", mysql.VARCHAR(20), nullable=True),
        sa.Column("prompt_ref", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("pending", "answered", "expired", name="agent_input_status"), nullable=False, server_default="pending"),
        sa.Column("answer_ref", sa.Text(), nullable=True),
        sa.Column("answered_by", mysql.VARCHAR(32), nullable=True),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "input_key", name="uk_agent_input_key"),
        sa.Index("idx_agent_input_run", "run_id"),
        comment="Agent 输入表：结构化澄清、范围选择和其他等待用户输入",
    )

    # ========================== agent_approvals ==========================
    op.create_table(
        "agent_approvals",
        sa.Column("id", mysql.VARCHAR(32), nullable=False),
        sa.Column("run_id", mysql.VARCHAR(32), nullable=False),
        sa.Column("action_key", mysql.VARCHAR(80), nullable=False),
        sa.Column("status", sa.Enum("pending", "approved", "rejected", "expired", name="agent_approval_status"), nullable=False, server_default="pending"),
        sa.Column("diff_ref", sa.Text(), nullable=True),
        sa.Column("precondition_ref", sa.Text(), nullable=True),
        sa.Column("decided_by", mysql.VARCHAR(32), nullable=True),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.Index("idx_agent_approval_run", "run_id"),
        comment="Agent 审批表：计划审批等人工审批流程",
    )


def downgrade() -> None:
    op.drop_table("agent_approvals")
    op.drop_table("agent_inputs")
    op.drop_table("agent_artifacts")
    op.drop_table("agent_loop_turns")
    op.drop_table("agent_checkpoints")
    op.drop_table("agent_run_outbox")
    op.drop_table("agent_events")
    op.drop_table("agent_steps")
    op.drop_table("agent_runs")
    op.drop_table("agent_threads")
