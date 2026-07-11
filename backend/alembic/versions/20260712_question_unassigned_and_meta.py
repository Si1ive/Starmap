"""questions 允许无归属入库 + 抽取诊断元数据

- subject_id / chapter_id 改为 nullable，FK ondelete CASCADE→SET NULL
  （组题成功但归属失败的题目也能入库，不再静默丢弃）
- 新增 extraction_meta JSON：记录组题来源/选项数/疑似截断等质量诊断

Revision ID: 20260712_q_unassigned_meta
Revises: 20260627_keyword_match_source
Create Date: 2026-07-12 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260712_q_unassigned_meta'
down_revision: Union[str, Sequence[str], None] = '20260627_keyword_match_source'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 先删除原 FK（CASCADE），改列为 nullable，再以 SET NULL 重建 FK
    op.drop_constraint('questions_ibfk_1', 'questions', type_='foreignkey')
    op.drop_constraint('questions_ibfk_2', 'questions', type_='foreignkey')

    op.alter_column(
        'questions', 'subject_id',
        existing_type=sa.String(length=32),
        nullable=True,
        comment='所属学科ID（未归属时为空）',
    )
    op.alter_column(
        'questions', 'chapter_id',
        existing_type=sa.String(length=32),
        nullable=True,
        comment='所属章节ID（兼容旧接口，未归属时为空）',
    )

    op.create_foreign_key(
        'questions_ibfk_1', 'questions', 'subjects',
        ['subject_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'questions_ibfk_2', 'questions', 'chapters',
        ['chapter_id'], ['id'], ondelete='SET NULL',
    )

    # 2. 抽取诊断元数据
    op.add_column(
        'questions',
        sa.Column('extraction_meta', sa.JSON(), nullable=True, comment='抽取质量诊断：组题来源/选项数/疑似截断等'),
    )


def downgrade() -> None:
    op.drop_column('questions', 'extraction_meta')

    op.drop_constraint('questions_ibfk_1', 'questions', type_='foreignkey')
    op.drop_constraint('questions_ibfk_2', 'questions', type_='foreignkey')

    op.alter_column(
        'questions', 'subject_id',
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.alter_column(
        'questions', 'chapter_id',
        existing_type=sa.String(length=32),
        nullable=False,
    )

    op.create_foreign_key(
        'questions_ibfk_1', 'questions', 'subjects',
        ['subject_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'questions_ibfk_2', 'questions', 'chapters',
        ['chapter_id'], ['id'], ondelete='CASCADE',
    )
