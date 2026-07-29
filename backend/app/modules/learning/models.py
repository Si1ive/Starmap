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
