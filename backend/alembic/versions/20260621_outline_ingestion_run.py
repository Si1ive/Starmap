"""add outline ingestion run table

Revision ID: 20260621_outline_run
Revises: c9d2e3f4a5b6
Create Date: 2026-06-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '20260621_outline_run'
down_revision = 'c9d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'outline_ingestion_runs',
        sa.Column('id', sa.String(32), primary_key=True, comment='任务ID'),
        sa.Column('document_id', sa.String(32), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False, comment='源文档ID'),
        sa.Column('outline_id', sa.String(32), nullable=True, comment='生成的大纲ID（成功后填充）'),
        sa.Column('outline_name', sa.String(200), nullable=True, comment='大纲名称'),
        sa.Column('year', sa.Integer, nullable=True, comment='年份'),
        sa.Column('version', sa.String(20), nullable=True, comment='版本'),

        sa.Column('status', sa.Enum('pending', 'processing', 'done', 'partial', 'failed'),
                  default='pending', nullable=False, comment='任务状态：partial=部分成功'),

        sa.Column('total_subjects', sa.Integer, default=0, comment='总科目数'),
        sa.Column('processed_subjects', sa.Integer, default=0, comment='已处理科目数'),
        sa.Column('successful_subjects', sa.Integer, default=0, comment='成功处理科目数'),
        sa.Column('current_subject_name', sa.String(100), nullable=True, comment='当前处理科目'),

        sa.Column('created_chapters', sa.Integer, default=0, comment='总共创建章节数'),
        sa.Column('updated_chapters', sa.Integer, default=0, comment='总共更新章节数'),

        sa.Column('error_detail', sa.Text, nullable=True, comment='错误详情'),
        sa.Column('result_summary', mysql.JSON, nullable=True, comment='各科目处理结果摘要'),

        sa.Column('started_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now(), onupdate=sa.func.now(), nullable=False),

        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
        comment='大纲入库任务执行记录'
    )

    op.create_index('idx_outline_run_document', 'outline_ingestion_runs', ['document_id'])
    op.create_index('idx_outline_run_status', 'outline_ingestion_runs', ['status'])
    op.create_index('idx_outline_run_created', 'outline_ingestion_runs', ['created_at'])


def downgrade() -> None:
    op.drop_table('outline_ingestion_runs')
