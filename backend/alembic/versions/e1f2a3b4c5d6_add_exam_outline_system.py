"""add_exam_outline_system

Revision ID: e1f2a3b4c5d6
Revises: 9a22b23ff620
Create Date: 2026-06-15 12:00:00.000000

"""
from typing import Sequence, Union
from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = '9a22b23ff620'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 创建 exam_outlines 表
    op.create_table('exam_outlines',
        sa.Column('id', sa.String(32), nullable=False, comment='大纲ID'),
        sa.Column('name', sa.String(100), nullable=False, comment='大纲名称，如：2025年408考研大纲'),
        sa.Column('year', sa.Integer(), nullable=False, comment='考试年份'),
        sa.Column('version', sa.String(20), nullable=False, server_default='v1.0', comment='版本号'),
        sa.Column('description', sa.Text(), nullable=True, comment='大纲说明'),
        sa.Column('release_date', sa.Date(), nullable=True, comment='发布日期'),
        sa.Column('effective_date', sa.Date(), nullable=True, comment='生效日期'),
        sa.Column('status', sa.Enum('draft', 'active', 'archived'), nullable=False, server_default='draft', comment='状态'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='0', comment='是否默认大纲'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('year', 'version', name='uk_outline_year_version'),
        comment='考试大纲元信息表'
    )
    op.create_index('idx_outline_year', 'exam_outlines', ['year'])
    op.create_index('idx_outline_status', 'exam_outlines', ['status'])
    op.create_index('idx_outline_default', 'exam_outlines', ['is_default'])

    # 2. 扩展 canonical_chapters 表，添加大纲关联字段
    op.add_column('canonical_chapters',
        sa.Column('outline_id', sa.String(32), nullable=True, comment='所属大纲ID')
    )
    op.add_column('canonical_chapters',
        sa.Column('outline_code', sa.String(50), nullable=True, comment='大纲中的编号，如：1.1.1')
    )

    # 添加外键约束
    op.create_foreign_key(
        'fk_canonical_chapters_outline',
        'canonical_chapters', 'exam_outlines',
        ['outline_id'], ['id'],
        ondelete='CASCADE'
    )

    # 添加索引
    op.create_index('idx_canonical_chapters_outline', 'canonical_chapters', ['outline_id'])

    # 更新表注释
    op.execute("ALTER TABLE canonical_chapters COMMENT '标准章节表（考试大纲章节）'")

    # 3. 初始化默认大纲（2025年408）
    op.execute("""
        INSERT INTO exam_outlines (id, name, year, version, status, is_default, created_at, updated_at)
        VALUES ('outline_2025_v1', '2025年408考研大纲', 2025, 'v1.0', 'active', 1, NOW(), NOW())
    """)


def downgrade() -> None:
    # 回滚顺序相反

    # 1. 删除默认大纲数据
    op.execute("DELETE FROM exam_outlines WHERE id = 'outline_2025_v1'")

    # 2. 移除 canonical_chapters 的大纲关联
    op.drop_index('idx_canonical_chapters_outline', 'canonical_chapters')
    op.drop_constraint('fk_canonical_chapters_outline', 'canonical_chapters', type_='foreignkey')
    op.drop_column('canonical_chapters', 'outline_code')
    op.drop_column('canonical_chapters', 'outline_id')

    # 恢复表注释
    op.execute("ALTER TABLE canonical_chapters COMMENT '标准章节表'")

    # 3. 删除 exam_outlines 表
    op.drop_index('idx_outline_default', 'exam_outlines')
    op.drop_index('idx_outline_status', 'exam_outlines')
    op.drop_index('idx_outline_year', 'exam_outlines')
    op.drop_table('exam_outlines')
