"""为实体抽取任务增加单项重提取范围

Revision ID: 20260714_entity_reextract
Revises: 20260714_admin_auth
Create Date: 2026-07-14 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260714_entity_reextract"
down_revision: Union[str, Sequence[str], None] = "20260714_admin_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_extraction_runs",
        sa.Column(
            "scope",
            sa.Enum("document", "entity"),
            nullable=False,
            server_default="document",
            comment="抽取范围：整文档或单个实体",
        ),
    )
    op.add_column(
        "entity_extraction_runs",
        sa.Column(
            "target_entity_type",
            sa.Enum("knowledge_point", "question"),
            nullable=True,
            comment="单项重提取的实体类型",
        ),
    )
    op.add_column(
        "entity_extraction_runs",
        sa.Column(
            "target_entity_id",
            sa.String(length=32),
            nullable=True,
            comment="单项重提取的实体ID",
        ),
    )
    op.create_index(
        "idx_entity_extraction_runs_target",
        "entity_extraction_runs",
        [
            "document_id",
            "scope",
            "target_entity_type",
            "target_entity_id",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_entity_extraction_runs_target",
        table_name="entity_extraction_runs",
    )
    op.drop_column("entity_extraction_runs", "target_entity_id")
    op.drop_column("entity_extraction_runs", "target_entity_type")
    op.drop_column("entity_extraction_runs", "scope")
