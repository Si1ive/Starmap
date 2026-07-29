"""upgrade learning activity facts and mastery to evidence model

Revision ID: 20260729_learning_evidence_model
Revises: 20260729_remove_study_timing
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_learning_evidence_model"
down_revision: Union[str, Sequence[str], None] = "20260729_remove_study_timing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """先回填兼容值，再把新证据/状态列收紧为应用契约。"""
    op.add_column(
        "learning_activity_events",
        sa.Column("evidence_type", sa.String(32), nullable=True),
    )
    op.add_column(
        "learning_activity_events",
        sa.Column("evidence_outcome", sa.String(24), nullable=True),
    )
    op.add_column(
        "learning_activity_events",
        sa.Column("assessment_source", sa.String(32), nullable=True),
    )
    op.add_column(
        "learning_activity_events",
        sa.Column("evidence_strength", sa.Float(), nullable=True),
    )
    op.add_column(
        "learning_activity_events",
        sa.Column("assessment_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "learning_activity_events",
        sa.Column("model_version", sa.String(64), nullable=True),
    )
    op.add_column(
        "learning_activity_events",
        sa.Column("knowledge_point_coverage_json", sa.JSON(), nullable=True),
    )
    op.execute(sa.text("""
            UPDATE learning_activity_events
            SET
                evidence_type = CASE
                    WHEN event_type = 'agent_explanation_completed'
                        OR is_correct IS NULL THEN 'exposure'
                    ELSE 'objective_assessment'
                END,
                evidence_outcome = CASE
                    WHEN is_correct = 1 THEN 'correct'
                    WHEN is_correct = 0 THEN 'incorrect'
                    ELSE 'unknown'
                END,
                assessment_source = CASE
                    WHEN is_correct IS NULL THEN NULL
                    ELSE 'deterministic'
                END,
                evidence_strength = CASE
                    WHEN is_correct IS NULL THEN 0
                    ELSE 1
                END,
                assessment_confidence = CASE
                    WHEN is_correct IS NULL THEN NULL
                    ELSE 1
                END
            """))
    op.alter_column(
        "learning_activity_events",
        "evidence_type",
        existing_type=sa.String(32),
        nullable=False,
        server_default="observation",
    )
    op.alter_column(
        "learning_activity_events",
        "evidence_outcome",
        existing_type=sa.String(24),
        nullable=False,
        server_default="unknown",
    )
    op.alter_column(
        "learning_activity_events",
        "evidence_strength",
        existing_type=sa.Float(),
        nullable=False,
        server_default="0",
    )

    op.add_column(
        "user_learning_mastery",
        sa.Column("mastery_alpha", sa.Float(), nullable=True),
    )
    op.add_column(
        "user_learning_mastery",
        sa.Column("mastery_beta", sa.Float(), nullable=True),
    )
    op.add_column(
        "user_learning_mastery",
        sa.Column("evidence_mass", sa.Float(), nullable=True),
    )
    op.add_column(
        "user_learning_mastery",
        sa.Column("uncertainty", sa.Float(), nullable=True),
    )
    op.add_column(
        "user_learning_mastery",
        sa.Column("last_evidence_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "user_learning_mastery",
        sa.Column("state_model_version", sa.String(32), nullable=True),
    )
    op.execute(sa.text("""
            UPDATE user_learning_mastery
            SET
                mastery_alpha = mastery_score * evidence_count,
                mastery_beta = (1 - mastery_score) * evidence_count,
                evidence_mass = evidence_count,
                uncertainty = CASE
                    WHEN evidence_count > 0 THEN 1 / SQRT(1 + evidence_count)
                    ELSE 1
                END,
                last_evidence_at = COALESCE(last_graded_at, updated_at, created_at),
                state_model_version = 'mastery-beta-v1'
            """))
    op.alter_column(
        "user_learning_mastery",
        "mastery_alpha",
        existing_type=sa.Float(),
        nullable=False,
        server_default="0",
    )
    op.alter_column(
        "user_learning_mastery",
        "mastery_beta",
        existing_type=sa.Float(),
        nullable=False,
        server_default="0",
    )
    op.alter_column(
        "user_learning_mastery",
        "evidence_mass",
        existing_type=sa.Float(),
        nullable=False,
        server_default="0",
    )
    op.alter_column(
        "user_learning_mastery",
        "uncertainty",
        existing_type=sa.Float(),
        nullable=False,
        server_default="1",
    )
    op.alter_column(
        "user_learning_mastery",
        "state_model_version",
        existing_type=sa.String(32),
        nullable=False,
        server_default="mastery-beta-v1",
    )


def downgrade() -> None:
    """移除阶段三字段，保留旧 mastery_score/quality 等兼容列。"""
    op.drop_column("user_learning_mastery", "state_model_version")
    op.drop_column("user_learning_mastery", "last_evidence_at")
    op.drop_column("user_learning_mastery", "uncertainty")
    op.drop_column("user_learning_mastery", "evidence_mass")
    op.drop_column("user_learning_mastery", "mastery_beta")
    op.drop_column("user_learning_mastery", "mastery_alpha")
    op.drop_column("learning_activity_events", "knowledge_point_coverage_json")
    op.drop_column("learning_activity_events", "model_version")
    op.drop_column("learning_activity_events", "assessment_confidence")
    op.drop_column("learning_activity_events", "evidence_strength")
    op.drop_column("learning_activity_events", "assessment_source")
    op.drop_column("learning_activity_events", "evidence_outcome")
    op.drop_column("learning_activity_events", "evidence_type")
