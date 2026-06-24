"""add_chapter_relations_table

Revision ID: 6829e5103e7a
Revises: a4e5e347237b
Create Date: 2026-06-24 14:57:16.657141

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6829e5103e7a'
down_revision: Union[str, Sequence[str], None] = 'a4e5e347237b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create chapter_relations table."""
    op.create_table(
        'chapter_relations',
        sa.Column('id', sa.String(32), primary_key=True, comment='关系ID'),
        sa.Column('source_chapter_id', sa.String(32), sa.ForeignKey('canonical_chapters.id', ondelete='CASCADE'), nullable=False, comment='源考点ID'),
        sa.Column('target_chapter_id', sa.String(32), sa.ForeignKey('canonical_chapters.id', ondelete='CASCADE'), nullable=False, comment='目标考点ID'),
        sa.Column('relation_type', sa.Enum('similar_to', 'prerequisite', 'contrast_with', 'common_confusion'), nullable=False, comment='关系类型'),
        sa.Column('confidence', sa.DECIMAL(5, 4), nullable=True, comment='置信度'),
        sa.Column('source_type', sa.Enum('llm', 'embedding', 'manual'), nullable=False, server_default='llm', comment='来源类型'),
        sa.Column('evidence_text', sa.Text, nullable=True, comment='证据文本'),
        sa.Column('review_status', sa.Enum('pending', 'approved', 'rejected'), nullable=False, server_default='pending', comment='审核状态'),
        sa.Column('review_notes', sa.Text, nullable=True, comment='审核备注'),
        sa.Column('reviewed_by', sa.String(32), nullable=True, comment='审核人'),
        sa.Column('reviewed_at', sa.DateTime, nullable=True, comment='审核时间'),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
    )
    op.create_index('idx_chrel_source', 'chapter_relations', ['source_chapter_id'])
    op.create_index('idx_chrel_target', 'chapter_relations', ['target_chapter_id'])
    op.create_index('idx_chrel_type', 'chapter_relations', ['relation_type'])
    op.create_index('idx_chrel_review_status', 'chapter_relations', ['review_status'])
    op.create_unique_constraint('uk_chapter_relation', 'chapter_relations', ['source_chapter_id', 'target_chapter_id', 'relation_type'])


def downgrade() -> None:
    """Drop chapter_relations table."""
    op.drop_table('chapter_relations')
