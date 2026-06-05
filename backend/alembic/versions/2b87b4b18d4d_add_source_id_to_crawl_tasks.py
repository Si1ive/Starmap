"""add source_id to crawl_tasks

Revision ID: 2b87b4b18d4d
Revises: 0a946c4cac4a
Create Date: 2026-06-05 18:04:22.339309

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2b87b4b18d4d'
down_revision: Union[str, Sequence[str], None] = '0a946c4cac4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 检查 source_id 字段是否已存在
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('crawl_tasks')]
    
    if 'source_id' not in columns:
        op.add_column('crawl_tasks', sa.Column('source_id', sa.String(32), nullable=True, comment='数据源ID'))
        op.create_index('idx_crawl_task_source_id', 'crawl_tasks', ['source_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # 检查 source_id 字段是否存在
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('crawl_tasks')]
    
    if 'source_id' in columns:
        op.drop_index('idx_crawl_task_source_id', table_name='crawl_tasks')
        op.drop_column('crawl_tasks', 'source_id')
