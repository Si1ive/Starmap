"""add outline llm: exam_outline_subjects table + canonical_chapters.exam_guidance

Revision ID: b8e1c2d3f4a5
Revises: a7da50f55004
Create Date: 2026-06-18 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e1c2d3f4a5'
down_revision: Union[str, Sequence[str], None] = 'a7da50f55004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新建 exam_outline_subjects 表 + canonical_chapters 增加 exam_guidance 列。"""
    op.create_table(
        'exam_outline_subjects',
        sa.Column('id', sa.String(length=32), nullable=False, comment='关联ID'),
        sa.Column('outline_id', sa.String(length=32), nullable=False, comment='所属大纲ID'),
        sa.Column('subject_id', sa.String(length=32), nullable=False, comment='所属学科ID'),
        sa.Column('exam_objective', sa.Text(), nullable=True, comment='该门课考察目标原文（概括性，三四句）'),
        sa.Column(
            'guidance_status',
            sa.Enum('pending', 'generating', 'done', 'failed'),
            nullable=False,
            server_default='pending',
            comment='复习指导批量生成状态',
        ),
        sa.Column('chapter_count', sa.Integer(), nullable=False, server_default='0', comment='该门课章节数'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['outline_id'], ['exam_outlines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('outline_id', 'subject_id', name='uk_outline_subject'),
        comment='大纲-科目关联表（考察目标）',
    )
    op.create_index('idx_outline_subject_outline', 'exam_outline_subjects', ['outline_id'])
    op.create_index('idx_outline_subject_subject', 'exam_outline_subjects', ['subject_id'])

    op.add_column(
        'canonical_chapters',
        sa.Column('exam_guidance', sa.Text(), nullable=True, comment='LLM 生成的复习指导（重点内容/复习方向）'),
    )


def downgrade() -> None:
    op.drop_column('canonical_chapters', 'exam_guidance')
    op.drop_index('idx_outline_subject_subject', table_name='exam_outline_subjects')
    op.drop_index('idx_outline_subject_outline', table_name='exam_outline_subjects')
    op.drop_table('exam_outline_subjects')
