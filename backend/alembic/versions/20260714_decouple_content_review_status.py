"""解耦题目/知识点可用状态与人工审核状态

Revision ID: 20260714_review_decoupled
Revises: 20260714_entity_extraction_runs
Create Date: 2026-07-14 02:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260714_review_decoupled"
down_revision: Union[str, Sequence[str], None] = "20260714_entity_extraction_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONTENT_STATUS = sa.Enum("active", "pending", "deleted")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    knowledge_columns = {
        column["name"] for column in inspector.get_columns("knowledge_points")
    }
    question_columns = {
        column["name"] for column in inspector.get_columns("questions")
    }

    if "reviewed_by" not in knowledge_columns:
        op.add_column(
            "knowledge_points",
            sa.Column(
                "reviewed_by",
                sa.String(length=32),
                nullable=True,
                comment="审核人",
            ),
        )
    if "reviewed_at" not in knowledge_columns:
        op.add_column(
            "knowledge_points",
            sa.Column("reviewed_at", sa.DateTime(), nullable=True, comment="审核时间"),
        )
    if "reviewed_by" not in question_columns:
        op.add_column(
            "questions",
            sa.Column(
                "reviewed_by",
                sa.String(length=32),
                nullable=True,
                comment="审核人",
            ),
        )
    if "reviewed_at" not in question_columns:
        op.add_column(
            "questions",
            sa.Column("reviewed_at", sa.DateTime(), nullable=True, comment="审核时间"),
        )

    # 历史 pending 是旧审核门禁产生的，不代表人工下线。保留 review_status，
    # 仅把业务可用状态回填为 active。
    op.execute(
        sa.text("UPDATE knowledge_points SET status = 'active' WHERE status = 'pending'")
    )
    op.execute(
        sa.text("UPDATE questions SET status = 'active' WHERE status = 'pending'")
    )

    op.alter_column(
        "knowledge_points",
        "status",
        existing_type=CONTENT_STATUS,
        existing_nullable=False,
        server_default="active",
        comment="可用状态；与人工审核状态独立",
    )
    op.alter_column(
        "questions",
        "status",
        existing_type=CONTENT_STATUS,
        existing_nullable=False,
        server_default="active",
        comment="可用状态；与人工审核状态独立",
    )


def downgrade() -> None:
    op.alter_column(
        "questions",
        "status",
        existing_type=CONTENT_STATUS,
        existing_nullable=False,
        server_default="pending",
        comment="状态",
    )
    op.alter_column(
        "knowledge_points",
        "status",
        existing_type=CONTENT_STATUS,
        existing_nullable=False,
        server_default="pending",
        comment="状态",
    )
    inspector = sa.inspect(op.get_bind())
    question_columns = {
        column["name"] for column in inspector.get_columns("questions")
    }
    knowledge_columns = {
        column["name"] for column in inspector.get_columns("knowledge_points")
    }

    if "reviewed_at" in question_columns:
        op.drop_column("questions", "reviewed_at")
    if "reviewed_by" in question_columns:
        op.drop_column("questions", "reviewed_by")
    if "reviewed_at" in knowledge_columns:
        op.drop_column("knowledge_points", "reviewed_at")
    if "reviewed_by" in knowledge_columns:
        op.drop_column("knowledge_points", "reviewed_by")
