"""add chapter link fields

Revision ID: 20260621_chapter_link_fields
Revises: 20260621_chapter_enhance
Create Date: 2026-06-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '20260621_chapter_link_fields'
down_revision = '20260621_chapter_enhance'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 为 knowledge_point_chapter_links 添加字段
    op.add_column('knowledge_point_chapter_links',
        sa.Column('relevance', sa.DECIMAL(5, 4), nullable=False, server_default='1.0000',
                  comment='关联度 [0,1]'))
    op.add_column('knowledge_point_chapter_links',
        sa.Column('source', sa.Enum('existing', 'document_mapping', 'vector_search', 'manual'),
                  nullable=False, server_default='manual',
                  comment='关联来源'))
    op.add_column('knowledge_point_chapter_links',
        sa.Column('created_by', sa.String(50), nullable=True,
                  comment='创建方式（system/user）'))

    # 为 question_chapter_links 添加字段
    op.add_column('question_chapter_links',
        sa.Column('relevance', sa.DECIMAL(5, 4), nullable=False, server_default='1.0000',
                  comment='关联度 [0,1]'))
    op.add_column('question_chapter_links',
        sa.Column('source', sa.Enum('existing', 'document_mapping', 'vector_search', 'manual'),
                  nullable=False, server_default='manual',
                  comment='关联来源'))
    op.add_column('question_chapter_links',
        sa.Column('created_by', sa.String(50), nullable=True,
                  comment='创建方式（system/user）'))


def downgrade() -> None:
    op.drop_column('question_chapter_links', 'created_by')
    op.drop_column('question_chapter_links', 'source')
    op.drop_column('question_chapter_links', 'relevance')

    op.drop_column('knowledge_point_chapter_links', 'created_by')
    op.drop_column('knowledge_point_chapter_links', 'source')
    op.drop_column('knowledge_point_chapter_links', 'relevance')
