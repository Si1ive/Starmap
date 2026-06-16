"""merge heads

Revision ID: 8556e83a6822
Revises: c3d4e5f6a7b8, e1f2a3b4c5d6
Create Date: 2026-06-16 16:50:50.144544

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8556e83a6822'
down_revision: Union[str, Sequence[str], None] = ('c3d4e5f6a7b8', 'e1f2a3b4c5d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
