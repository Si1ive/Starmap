"""add_cross_references_to_canonical_chapters

Revision ID: a4e5e347237b
Revises: eaa99a3c14cd
Create Date: 2026-06-24 02:57:47.900343

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4e5e347237b'
down_revision: Union[str, Sequence[str], None] = 'eaa99a3c14cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add cross_references JSON column to canonical_chapters."""
    op.add_column(
        'canonical_chapters',
        sa.Column(
            'cross_references',
            sa.JSON(),
            nullable=True,
            comment='LLM 标注的跨章节考点关联。每项含 target_chapter_id/relation_type/reason'
        )
    )


def downgrade() -> None:
    """Remove cross_references column from canonical_chapters."""
    op.drop_column('canonical_chapters', 'cross_references')
