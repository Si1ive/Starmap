"""merge_heads

Revision ID: 6bdec4564340
Revises: 2b87b4b18d4d, a1b2c3d4e5f6
Create Date: 2026-06-10 17:30:09.656393

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6bdec4564340'
down_revision: Union[str, Sequence[str], None] = ('2b87b4b18d4d', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
