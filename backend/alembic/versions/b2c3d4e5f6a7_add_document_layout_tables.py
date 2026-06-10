"""add_document_layout_tables

Revision ID: b2c3d4e5f6a7
Revises: 9a22b23ff620
Create Date: 2026-06-10 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = '9a22b23ff620'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # document_pages
    op.create_table('document_pages',
        sa.Column('id', sa.String(32), nullable=False, comment='页ID'),
        sa.Column('document_id', sa.String(32), nullable=False, comment='文档ID'),
        sa.Column('page_no', sa.Integer(), nullable=False, comment='页码，从1开始'),
        sa.Column('page_image_path', sa.String(500), nullable=True, comment='页截图路径'),
        sa.Column('width', sa.Integer(), nullable=True, comment='宽度'),
        sa.Column('height', sa.Integer(), nullable=True, comment='高度'),
        sa.Column('rotation', sa.Integer(), nullable=True, comment='旋转角度'),
        sa.Column('ocr_text', sa.Text(), nullable=True, comment='页级OCR文本'),
        sa.Column('layout_json', sa.JSON(), nullable=True, comment='布局信息'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id', 'page_no', name='uk_document_pages_doc_page'),
        comment='文档页表'
    )
    op.create_index('idx_document_pages_document_id', 'document_pages', ['document_id'])

    # document_assets
    op.create_table('document_assets',
        sa.Column('id', sa.String(32), nullable=False, comment='资产ID'),
        sa.Column('document_id', sa.String(32), nullable=False, comment='文档ID'),
        sa.Column('page_no', sa.Integer(), nullable=False, comment='页码'),
        sa.Column('asset_type', sa.Enum('figure', 'table', 'formula', 'page_crop', 'other'), nullable=False, comment='资产类型'),
        sa.Column('file_path', sa.String(500), nullable=False, comment='资产文件路径'),
        sa.Column('thumbnail_path', sa.String(500), nullable=True, comment='缩略图路径'),
        sa.Column('bbox', sa.JSON(), nullable=True, comment='坐标'),
        sa.Column('caption_text', sa.Text(), nullable=True, comment='图表标题'),
        sa.Column('ocr_text', sa.Text(), nullable=True, comment='图内OCR结果'),
        sa.Column('metadata_json', sa.JSON(), nullable=True, comment='扩展元数据'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='文档图表公式资产表'
    )
    op.create_index('idx_document_assets_document_page', 'document_assets', ['document_id', 'page_no'])
    op.create_index('idx_document_assets_type', 'document_assets', ['asset_type'])

    # document_blocks
    op.create_table('document_blocks',
        sa.Column('id', sa.String(32), nullable=False, comment='块ID'),
        sa.Column('document_id', sa.String(32), nullable=False, comment='文档ID'),
        sa.Column('page_id', sa.String(32), nullable=True, comment='页ID'),
        sa.Column('page_no', sa.Integer(), nullable=False, comment='页码'),
        sa.Column('block_type', sa.String(50), nullable=False, comment='块类型'),
        sa.Column('order_no', sa.Integer(), nullable=False, comment='页内顺序'),
        sa.Column('bbox', sa.JSON(), nullable=True, comment='坐标'),
        sa.Column('content_text', sa.Text(), nullable=True, comment='纯文本'),
        sa.Column('content_md', sa.Text(), nullable=True, comment='Markdown表示'),
        sa.Column('content_json', sa.JSON(), nullable=True, comment='结构化表示'),
        sa.Column('latex', sa.Text(), nullable=True, comment='公式LaTeX'),
        sa.Column('html_table', sa.Text(), nullable=True, comment='表格HTML'),
        sa.Column('asset_id', sa.String(32), nullable=True, comment='关联资产ID'),
        sa.Column('confidence', sa.DECIMAL(5, 4), nullable=True, comment='识别置信度'),
        sa.Column('review_status', sa.Enum('pending', 'approved', 'rejected'), nullable=False, comment='审核状态'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='文档块表'
    )
    op.create_index('idx_document_blocks_document_page', 'document_blocks', ['document_id', 'page_no'])
    op.create_index('idx_document_blocks_type', 'document_blocks', ['block_type'])
    op.create_index('idx_document_blocks_review_status', 'document_blocks', ['review_status'])


def downgrade() -> None:
    op.drop_table('document_blocks')
    op.drop_table('document_assets')
    op.drop_table('document_pages')
