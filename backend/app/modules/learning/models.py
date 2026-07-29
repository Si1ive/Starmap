"""Durable, user-owned learning activity facts."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base
from app.db.types import UUIDBinary


class LearningActivityEvent(Base):
    __tablename__ = "learning_activity_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[object] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(96), nullable=False)
    thread_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("agent_threads.id", ondelete="SET NULL")
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    topic_keywords_json: Mapped[list] = mapped_column(JSON, nullable=False)
    knowledge_point_ids_json: Mapped[Optional[list]] = mapped_column(JSON)
    evidence_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="observation",
        server_default="observation",
        comment="结构化证据行为类型",
    )
    evidence_outcome: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="unknown",
        server_default="unknown",
        comment="结构化证据结果",
    )
    assessment_source: Mapped[Optional[str]] = mapped_column(
        String(32), comment="评价或题目来源"
    )
    evidence_strength: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0",
        comment="服务端裁剪后的证据强度",
    )
    assessment_confidence: Mapped[Optional[float]] = mapped_column(
        Float, comment="评价置信度，不等同于掌握度"
    )
    model_version: Mapped[Optional[str]] = mapped_column(
        String(64), comment="产生评价或题目的模型版本"
    )
    knowledge_point_coverage_json: Mapped[Optional[dict]] = mapped_column(
        JSON, comment="知识点 coverage 分摊权重"
    )
    quality: Mapped[float] = mapped_column(Float, nullable=False)
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "event_type",
            "source_id",
            name="uk_learning_activity_source",
        ),
        Index("idx_learning_activity_user_time", "user_id", "occurred_at"),
        Index("idx_learning_activity_thread", "thread_id", "occurred_at"),
        Index("idx_learning_activity_run", "run_id"),
    )

    def to_learning_evidence(self):
        """按兼容规则读取为自适应学习证据，不修改当前活动事实。"""

        from .contracts import LearningEvidence

        return LearningEvidence.from_legacy_activity_event(self)
