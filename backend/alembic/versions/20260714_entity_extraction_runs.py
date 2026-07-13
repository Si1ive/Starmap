"""新增实体抽取运行记录表

Revision ID: 20260714_entity_extraction_runs
Revises: 20260712_vector_recall_logs
Create Date: 2026-07-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260714_entity_extraction_runs"
down_revision: Union[str, Sequence[str], None] = "20260712_vector_recall_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_extraction_runs",
        sa.Column("id", sa.String(length=32), nullable=False, comment="抽取任务ID"),
        sa.Column("document_id", sa.String(length=32), nullable=False, comment="文档ID"),
        sa.Column(
            "status",
            sa.Enum("running", "success", "failed"),
            nullable=False,
            comment="执行状态",
        ),
        sa.Column("extract_knowledge", sa.Boolean(), nullable=False, comment="是否抽取知识点"),
        sa.Column("extract_questions", sa.Boolean(), nullable=False, comment="是否抽取题目"),
        sa.Column("subject_id", sa.String(length=32), nullable=True, comment="兜底学科ID"),
        sa.Column("knowledge_count", sa.Integer(), nullable=False, comment="抽取知识点数"),
        sa.Column("question_count", sa.Integer(), nullable=False, comment="抽取题目数"),
        sa.Column("error_detail", sa.Text(), nullable=True, comment="失败原因"),
        sa.Column("result_json", sa.JSON(), nullable=True, comment="完整抽取结果"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="文档实体抽取执行记录",
    )
    op.create_index(
        "idx_entity_extraction_runs_document_id",
        "entity_extraction_runs",
        ["document_id"],
    )
    op.create_index(
        "idx_entity_extraction_runs_status",
        "entity_extraction_runs",
        ["status"],
    )
    op.create_index(
        "idx_entity_extraction_runs_created_at",
        "entity_extraction_runs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_entity_extraction_runs_created_at",
        table_name="entity_extraction_runs",
    )
    op.drop_index(
        "idx_entity_extraction_runs_status",
        table_name="entity_extraction_runs",
    )
    op.drop_index(
        "idx_entity_extraction_runs_document_id",
        table_name="entity_extraction_runs",
    )
    op.drop_table("entity_extraction_runs")
