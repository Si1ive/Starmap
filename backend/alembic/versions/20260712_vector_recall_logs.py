"""新增 vector_recall_logs 表：记录向量召回日志

记录每次 Qdrant 章节召回的入参 query、top-N 结果与分数，
供监控页分析召回质量与命中率。仿照 llm_call_logs 的可观测日志模式，
但字段贴合向量检索语义（无 model/token/cost）。

Revision ID: 20260712_vector_recall_logs
Revises: 20260712_q_unassigned_meta
Create Date: 2026-07-12 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260712_vector_recall_logs'
down_revision: Union[str, Sequence[str], None] = '20260712_q_unassigned_meta'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vector_recall_logs',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('called_by', sa.String(length=100), nullable=True, comment='调用方：question / knowledge_point'),
        sa.Column('purpose', sa.String(length=100), nullable=True, comment='召回用途说明'),
        sa.Column('query_text', sa.Text(), nullable=True, comment='向量化的查询文本（入参）'),
        sa.Column('query_entity_id', sa.String(length=32), nullable=True, comment='触发召回的题目/知识点ID'),
        sa.Column('subject_id', sa.String(length=32), nullable=True, comment='检索范围学科ID（空=全学科）'),
        sa.Column('top_results', sa.JSON(), nullable=True, comment='top-N 召回结果'),
        sa.Column('top_score', sa.DECIMAL(precision=6, scale=4), nullable=True, comment='最高召回分数'),
        sa.Column('result_count', sa.Integer(), nullable=True, comment='召回结果数'),
        sa.Column('threshold_hit', sa.Boolean(), nullable=True, comment='最高分是否达到采信阈值'),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.Enum('hit', 'miss', 'error'), nullable=True, comment='召回状态'),
        sa.Column('error_msg', sa.Text(), nullable=True, comment='错误信息'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        comment='向量召回日志',
    )
    op.create_index('idx_vec_recall_created_at', 'vector_recall_logs', ['created_at'])
    op.create_index('idx_vec_recall_called_by', 'vector_recall_logs', ['called_by'])
    op.create_index('idx_vec_recall_status', 'vector_recall_logs', ['status'])


def downgrade() -> None:
    op.drop_index('idx_vec_recall_status', table_name='vector_recall_logs')
    op.drop_index('idx_vec_recall_called_by', table_name='vector_recall_logs')
    op.drop_index('idx_vec_recall_created_at', table_name='vector_recall_logs')
    op.drop_table('vector_recall_logs')
