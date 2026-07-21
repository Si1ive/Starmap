"""
Agent 核心数据模型（ORM + Pydantic Schema）

P0 最小可用核心：Thread / Run / Step / Event / Outbox / Checkpoint
"""

from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import (
    String, Text, DateTime, Integer, ForeignKey, Index, UniqueConstraint, Enum as SAEnum, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base


# ========================== ORM Models ==========================

class AgentThread(Base):
    """线程表：用户对话容器"""
    __tablename__ = "agent_threads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="用户ID")
    title: Mapped[Optional[str]] = mapped_column(String(255), comment="线程标题")
    status: Mapped[str] = mapped_column(
        SAEnum("active", "archived", "deleted"),
        default="active",
        comment="线程状态"
    )
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="扩展元数据")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_agent_thread_user", "user_id"),
        Index("idx_agent_thread_status", "status"),
        {"comment": "Agent 线程表"}
    )


class AgentRun(Base):
    """执行记录表：单次工作流实例"""
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_threads.id", ondelete="CASCADE"),
        nullable=False, comment="所属线程ID"
    )
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="用户ID")
    workflow_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="工作流名称")
    status: Mapped[str] = mapped_column(
        SAEnum("queued", "running", "completed", "failed", "waiting_for_user"),
        default="queued",
        comment="运行状态"
    )
    input_message: Mapped[Optional[str]] = mapped_column(Text, comment="用户输入")
    result_artifact_id: Mapped[Optional[str]] = mapped_column(String(32), comment="产物ID")
    error_message: Mapped[Optional[str]] = mapped_column(Text, comment="错误信息")
    model_call_count: Mapped[int] = mapped_column(Integer, default=0, comment="模型调用次数")
    max_model_calls: Mapped[int] = mapped_column(Integer, default=6, comment="最大模型调用数")
    lease_owner: Mapped[Optional[str]] = mapped_column(String(64), comment="租约持有者标识")
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="租约过期时间")
    client_idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(64), comment="客户端幂等键"
    )
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="扩展元数据")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_agent_run_thread", "thread_id"),
        Index("idx_agent_run_user", "user_id"),
        Index("idx_agent_run_status", "status"),
        Index("idx_agent_run_lease", "lease_owner", "lease_expires_at"),
        UniqueConstraint("user_id", "client_idempotency_key", name="uk_agent_run_idempotency"),
        {"comment": "Agent 执行记录表"}
    )


class AgentStep(Base):
    """步骤表：工作流中的节点执行记录"""
    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False, comment="所属运行ID"
    )
    parent_step_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("agent_steps.id", ondelete="SET NULL"),
        comment="父步骤ID"
    )
    node_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="节点名称")
    node_type: Mapped[str] = mapped_column(
        SAEnum("router", "action", "gate", "loop", "render", "wait"),
        nullable=False, comment="节点类型"
    )
    status: Mapped[str] = mapped_column(
        SAEnum("pending", "running", "completed", "failed", "skipped"),
        default="pending",
        comment="步骤状态"
    )
    input_data: Mapped[Optional[dict]] = mapped_column(JSON, comment="输入数据")
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, comment="输出数据")
    error_info: Mapped[Optional[dict]] = mapped_column(JSON, comment="错误信息")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="开始时间")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="完成时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_step_run", "run_id"),
        Index("idx_agent_step_parent", "parent_step_id"),
        {"comment": "Agent 步骤表"}
    )


class AgentEvent(Base):
    """事件表：SSE 推送的事实源，sequence 单调递增"""
    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False, comment="所属运行ID"
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, comment="事件序号（单调递增）")
    event_type: Mapped[str] = mapped_column(
        SAEnum(
            "run.created", "run.status_changed", "run.completed",
            "step.started", "step.completed", "step.failed",
            "tool.called", "tool.result",
            "message.delta", "message.completed",
            "artifact.rendered", "error"
        ),
        nullable=False, comment="事件类型"
    )
    payload: Mapped[Optional[dict]] = mapped_column(JSON, comment="事件负载")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_event_run", "run_id"),
        UniqueConstraint("run_id", "sequence", name="uk_agent_event_seq"),
        {"comment": "Agent 事件表"}
    )


class AgentRunOutbox(Base):
    """Outbox 表：任务唤醒队列（Worker 扫描）"""
    __tablename__ = "agent_run_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False, comment="运行ID"
    )
    status: Mapped[str] = mapped_column(
        SAEnum("pending", "processing", "completed", "failed"),
        default="pending",
        comment="处理状态"
    )
    worker_id: Mapped[Optional[str]] = mapped_column(String(64), comment="处理Worker标识")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, comment="重试次数")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, comment="计划执行时间")
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="处理时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_outbox_status", "status", "scheduled_at"),
        Index("idx_agent_outbox_run", "run_id"),
        {"comment": "Agent Outbox 表"}
    )


class AgentCheckpoint(Base):
    """断点表：崩溃恢复用"""
    __tablename__ = "agent_checkpoints"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False, comment="所属运行ID"
    )
    context_json: Mapped[dict] = mapped_column(JSON, comment="上下文JSON（可恢复状态）")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_checkpoint_run", "run_id"),
        {"comment": "Agent 断点表"}
    )


class AgentLoopTurn(Base):
    """Loop 决策与 observation 持久化"""
    __tablename__ = "agent_loop_turns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False, comment="所属运行ID"
    )
    parent_step_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("agent_steps.id", ondelete="SET NULL"),
        comment="父步骤ID"
    )
    turn_no: Mapped[int] = mapped_column(Integer, default=0, comment="轮次编号")
    decision_ref: Mapped[Optional[str]] = mapped_column(Text, comment="决策JSON（动作+推理）")
    action_key: Mapped[Optional[str]] = mapped_column(String(50), comment="执行的Action键")
    observation_ref: Mapped[Optional[str]] = mapped_column(Text, comment="Observation结果JSON")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_loop_run", "run_id"),
        UniqueConstraint("run_id", "turn_no", name="uk_agent_loop_turn"),
        {"comment": "Agent Loop 决策表"}
    )


class AgentArtifact(Base):
    """产物表：渲染产物"""
    __tablename__ = "agent_artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False, comment="所属运行ID"
    )
    artifact_type: Mapped[str] = mapped_column(
        SAEnum("explanation", "practice", "feedback", "plan", "message"),
        nullable=False, comment="产物类型"
    )
    content_json: Mapped[dict] = mapped_column(JSON, comment="产物内容")
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="扩展元数据")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_agent_artifact_run", "run_id"),
        {"comment": "Agent 产物表"}
    )


class AgentInput(Base):
    """输入表：结构化澄清、范围选择和其他等待用户输入"""
    __tablename__ = "agent_inputs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False, comment="所属运行ID"
    )
    input_key: Mapped[str] = mapped_column(String(80), nullable=False, comment="输入标识")
    input_schema_version: Mapped[Optional[str]] = mapped_column(String(20), comment="输入Schema版本")
    prompt_ref: Mapped[Optional[str]] = mapped_column(Text, comment="提示内容引用")
    status: Mapped[str] = mapped_column(
        SAEnum("pending", "answered", "expired"),
        default="pending",
        comment="输入状态"
    )
    answer_ref: Mapped[Optional[str]] = mapped_column(Text, comment="用户答案引用")
    answered_by: Mapped[Optional[str]] = mapped_column(String(32), comment="回答者用户ID")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="过期时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_agent_input_run", "run_id"),
        UniqueConstraint("run_id", "input_key", name="uk_agent_input_key"),
        {"comment": "Agent 输入表"}
    )


class AgentApproval(Base):
    """审批表：计划审批等人工审批流程"""
    __tablename__ = "agent_approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False, comment="所属运行ID"
    )
    action_key: Mapped[str] = mapped_column(String(80), nullable=False, comment="审批动作标识")
    status: Mapped[str] = mapped_column(
        SAEnum("pending", "approved", "rejected", "expired"),
        default="pending",
        comment="审批状态"
    )
    diff_ref: Mapped[Optional[str]] = mapped_column(Text, comment="变更差异引用")
    precondition_ref: Mapped[Optional[str]] = mapped_column(Text, comment="前置条件引用")
    decided_by: Mapped[Optional[str]] = mapped_column(String(32), comment="审批者ID")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="过期时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_agent_approval_run", "run_id"),
        {"comment": "Agent 审批表"}
    )
