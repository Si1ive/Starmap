"""Persistent user-bound mock exam and focus timer models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base
from app.db.types import UUIDBinary


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[object] = mapped_column(
        UUIDBinary(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_document_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    mode: Mapped[str] = mapped_column(String(24), nullable=False, default="mock_exam")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    awarded_score: Mapped[Optional[int]] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_practice_sessions_user_created", "user_id", "created_at"),
        Index("idx_practice_sessions_user_status", "user_id", "status"),
    )


class PracticeSessionQuestion(Base):
    __tablename__ = "practice_session_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("practice_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "session_id", "question_id", name="uk_practice_session_question"
        ),
        UniqueConstraint("session_id", "order_no", name="uk_practice_session_order"),
    )


class PracticeAnswer(Base):
    __tablename__ = "practice_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("practice_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    user_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean)
    awarded_score: Mapped[Optional[int]] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("session_id", "question_id", name="uk_practice_answer"),
        Index("idx_practice_answers_question", "question_id"),
    )


class StudyTimerRecord(Base):
    __tablename__ = "study_timer_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[object] = mapped_column(
        UUIDBinary(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    planned_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    context_json: Mapped[Optional[dict]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (Index("idx_study_timer_user_started", "user_id", "started_at"),)
