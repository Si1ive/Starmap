"""add_source_section_path

Revision ID: 20260627_source_section_path
Revises: 6829e5103e7a
Create Date: 2026-06-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260627_source_section_path'
down_revision: Union[str, Sequence[str], None] = '6829e5103e7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'knowledge_points',
        sa.Column('source_section_path', sa.String(length=500), nullable=True, comment='识别出的原始章节路径'),
    )
    op.add_column(
        'questions',
        sa.Column('source_section_path', sa.String(length=500), nullable=True, comment='识别出的原始章节路径'),
    )


def downgrade() -> None:
    op.drop_column('questions', 'source_section_path')
    op.drop_column('knowledge_points', 'source_section_path')
