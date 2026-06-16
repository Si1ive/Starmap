"""add raw_parser_output to documents

Revision ID: a7da50f55004
Revises: 8556e83a6822
Create Date: 2026-06-16 16:52:38.086843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7da50f55004'
down_revision: Union[str, Sequence[str], None] = '8556e83a6822'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add raw_parser_output column to documents table."""
    op.add_column('documents', sa.Column('raw_parser_output', sa.JSON(), nullable=True, comment='解析器原始输出JSON'))


def downgrade() -> None:
    """Remove raw_parser_output column from documents table."""
    op.drop_column('documents', 'raw_parser_output')
