"""add chapter enhancement fields

Revision ID: 20260621_chapter_enhance
Revises: 20260621_outline_run
Create Date: 2026-06-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '20260621_chapter_enhance'
down_revision = '20260621_outline_run'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 为 canonical_chapters 表增加增强字段
    op.add_column('canonical_chapters',
        sa.Column('enhanced_description', sa.Text, nullable=True,
                  comment='LLM 增强描述（2-3句，含考法/易混点/核心内容，用于向量检索）'))
    op.add_column('canonical_chapters',
        sa.Column('keywords', mysql.JSON, nullable=True,
                  comment='关键词标签（别名、英文名、相关术语，用于精确匹配）'))


def downgrade() -> None:
    op.drop_column('canonical_chapters', 'keywords')
    op.drop_column('canonical_chapters', 'enhanced_description')
