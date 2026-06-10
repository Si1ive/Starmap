"""add_corpus_file_pipeline_tables

Revision ID: 9a22b23ff620
Revises: 6bdec4564340
Create Date: 2026-06-10 17:36:22.503516

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9a22b23ff620'
down_revision: Union[str, Sequence[str], None] = '6bdec4564340'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # corpus_files
    op.create_table('corpus_files',
        sa.Column('id', sa.String(32), nullable=False, comment='语料文件ID'),
        sa.Column('source_type', sa.Enum('crawler', 'manual', 'upload', 'import'), nullable=False, comment='来源类型'),
        sa.Column('source_ref', sa.String(255), nullable=True, comment='来源引用'),
        sa.Column('file_name', sa.String(255), nullable=False, comment='文件名'),
        sa.Column('file_ext', sa.String(20), nullable=False, comment='扩展名'),
        sa.Column('local_path', sa.String(500), nullable=False, comment='本地路径'),
        sa.Column('storage_uri', sa.String(500), nullable=True, comment='对象存储URI'),
        sa.Column('sha256', sa.String(64), nullable=False, comment='文件哈希'),
        sa.Column('file_size', sa.BigInteger(), nullable=True, comment='文件大小'),
        sa.Column('mime_type', sa.String(100), nullable=True, comment='MIME类型'),
        sa.Column('language', sa.String(20), nullable=True, comment='文档主语言'),
        sa.Column('doc_type', sa.Enum('textbook', 'past_exam', 'mock_exam', 'notes', 'other'), nullable=False, comment='文档业务类型'),
        sa.Column('version', sa.Integer(), nullable=False, comment='同源版本号'),
        sa.Column('status', sa.Enum('pending', 'parsing', 'parsed', 'extracting', 'indexed', 'failed', 'archived'), nullable=False, comment='处理状态'),
        sa.Column('error_detail', sa.Text(), nullable=True, comment='失败原因'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sha256', name='uk_corpus_files_sha256'),
        comment='统一语料文件注册表'
    )
    op.create_index('idx_corpus_files_status', 'corpus_files', ['status'])
    op.create_index('idx_corpus_files_source_type', 'corpus_files', ['source_type'])
    op.create_index('idx_corpus_files_doc_type', 'corpus_files', ['doc_type'])

    # parse_runs
    op.create_table('parse_runs',
        sa.Column('id', sa.String(32), nullable=False, comment='解析任务ID'),
        sa.Column('corpus_file_id', sa.String(32), nullable=False, comment='语料文件ID'),
        sa.Column('parser_name', sa.String(50), nullable=False, comment='解析器名称'),
        sa.Column('parser_version', sa.String(50), nullable=False, comment='解析器版本'),
        sa.Column('parse_mode', sa.Enum('primary', 'fallback', 'retry', 'manual_fix'), nullable=False, comment='解析模式'),
        sa.Column('status', sa.Enum('running', 'success', 'failed', 'partial'), nullable=False, comment='执行状态'),
        sa.Column('page_count', sa.Integer(), nullable=True, comment='识别页数'),
        sa.Column('block_count', sa.Integer(), nullable=True, comment='识别块数'),
        sa.Column('asset_count', sa.Integer(), nullable=True, comment='识别资产数'),
        sa.Column('confidence', sa.DECIMAL(5, 4), nullable=True, comment='整体置信度'),
        sa.Column('error_detail', sa.Text(), nullable=True, comment='错误信息'),
        sa.Column('metrics_json', sa.JSON(), nullable=True, comment='耗时与质量指标'),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['corpus_file_id'], ['corpus_files.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='文档解析执行记录'
    )
    op.create_index('idx_parse_runs_corpus_file_id', 'parse_runs', ['corpus_file_id'])
    op.create_index('idx_parse_runs_status', 'parse_runs', ['status'])

    # documents
    op.create_table('documents',
        sa.Column('id', sa.String(32), nullable=False, comment='文档ID'),
        sa.Column('corpus_file_id', sa.String(32), nullable=False, comment='文件ID'),
        sa.Column('latest_parse_run_id', sa.String(32), nullable=True, comment='最新成功解析ID'),
        sa.Column('title', sa.String(255), nullable=True, comment='文档标题'),
        sa.Column('doc_type', sa.Enum('textbook', 'past_exam', 'mock_exam', 'notes', 'other'), nullable=False, comment='文档类型'),
        sa.Column('subject_id', sa.String(32), nullable=True, comment='主学科ID'),
        sa.Column('source_label', sa.String(255), nullable=True, comment='展示来源'),
        sa.Column('exam_scope', sa.String(50), nullable=True, comment='例如408'),
        sa.Column('exam_year', sa.Integer(), nullable=True, comment='真题年份'),
        sa.Column('paper_name', sa.String(255), nullable=True, comment='试卷名'),
        sa.Column('language', sa.String(20), nullable=True, comment='文档语言'),
        sa.Column('page_count', sa.Integer(), nullable=True, comment='页数'),
        sa.Column('document_markdown', sa.Text(), nullable=True, comment='展示Markdown'),
        sa.Column('document_json', sa.JSON(), nullable=True, comment='结构化文档对象'),
        sa.Column('status', sa.Enum('active', 'pending', 'deleted'), nullable=False, comment='业务状态'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['corpus_file_id'], ['corpus_files.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='正规化文档主表'
    )
    op.create_index('idx_documents_corpus_file_id', 'documents', ['corpus_file_id'])
    op.create_index('idx_documents_subject_id', 'documents', ['subject_id'])
    op.create_index('idx_documents_exam_year', 'documents', ['exam_year'])
    op.create_index('idx_documents_doc_type', 'documents', ['doc_type'])
    op.create_index('idx_documents_status', 'documents', ['status'])


def downgrade() -> None:
    op.drop_table('documents')
    op.drop_table('parse_runs')
    op.drop_table('corpus_files')
