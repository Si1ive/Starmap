"""add_embedding_to_knowledge_relation_source_type

Revision ID: eaa99a3c14cd
Revises: 5ca0c7b42da3
Create Date: 2026-06-24 02:55:20.404042

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'eaa99a3c14cd'
down_revision: Union[str, Sequence[str], None] = '5ca0c7b42da3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'embedding' to knowledge_relations.source_type ENUM."""
    op.execute(
        "ALTER TABLE knowledge_relations MODIFY COLUMN source_type "
        "ENUM('rule','llm','manual','term_similarity','embedding') "
        "NOT NULL DEFAULT 'llm' COMMENT '来源类型'"
    )


def downgrade() -> None:
    """Revert source_type ENUM to original values."""
    op.execute(
        "ALTER TABLE knowledge_relations MODIFY COLUMN source_type "
        "ENUM('rule','llm','manual','term_similarity') "
        "NOT NULL DEFAULT 'llm' COMMENT '来源类型'"
    )
