"""enrichment: question/kp enrich fields + question_knowledge_links table

Revision ID: c9d2e3f4a5b6
Revises: b8e1c2d3f4a5
Create Date: 2026-06-20 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b8e1c2d3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """题目/知识点富化字段 + 题↔知识点关联表。"""
    # questions 加来源标记 + 富化状态
    op.add_column('questions', sa.Column(
        'answer_source',
        sa.Enum('none', 'extracted', 'llm', 'manual'),
        nullable=False, server_default='none', comment='答案来源',
    ))
    op.add_column('questions', sa.Column(
        'explanation_source',
        sa.Enum('none', 'extracted', 'llm', 'manual'),
        nullable=False, server_default='none', comment='解析来源',
    ))
    op.add_column('questions', sa.Column(
        'enrich_status',
        sa.Enum('pending', 'enriching', 'done', 'failed'),
        nullable=False, server_default='pending', comment='LLM 富化状态',
    ))

    # knowledge_points 加摘要 + 富化状态
    op.add_column('knowledge_points', sa.Column(
        'summary', sa.Text(), nullable=True, comment='LLM 一句话摘要（向量召回用）',
    ))
    op.add_column('knowledge_points', sa.Column(
        'enrich_status',
        sa.Enum('pending', 'enriching', 'done', 'failed'),
        nullable=False, server_default='pending', comment='LLM 富化状态',
    ))

    # 题↔知识点关联表
    op.create_table(
        'question_knowledge_links',
        sa.Column('id', sa.String(length=32), nullable=False, comment='关联ID'),
        sa.Column('question_id', sa.String(length=32), nullable=False, comment='题目ID'),
        sa.Column('knowledge_point_id', sa.String(length=32), nullable=False, comment='知识点ID'),
        sa.Column('relevance', sa.DECIMAL(precision=5, scale=4), nullable=False, server_default='0', comment='关联强度 0-1'),
        sa.Column('source', sa.Enum('llm', 'vector', 'rule', 'manual'), nullable=False, server_default='llm', comment='关联来源'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['knowledge_point_id'], ['knowledge_points.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('question_id', 'knowledge_point_id', name='uk_q_kp_link'),
        comment='题目与知识点关联表',
    )
    op.create_index('idx_qkl_question', 'question_knowledge_links', ['question_id'])
    op.create_index('idx_qkl_kp', 'question_knowledge_links', ['knowledge_point_id'])


def downgrade() -> None:
    op.drop_index('idx_qkl_kp', table_name='question_knowledge_links')
    op.drop_index('idx_qkl_question', table_name='question_knowledge_links')
    op.drop_table('question_knowledge_links')
    op.drop_column('knowledge_points', 'enrich_status')
    op.drop_column('knowledge_points', 'summary')
    op.drop_column('questions', 'enrich_status')
    op.drop_column('questions', 'explanation_source')
    op.drop_column('questions', 'answer_source')
