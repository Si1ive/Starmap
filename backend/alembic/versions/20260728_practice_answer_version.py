"""add optimistic versions to practice answers

Revision ID: 20260728_practice_answer_version
Revises: 20260728_user_source_controls
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_practice_answer_version"
down_revision: Union[str, Sequence[str], None] = "20260728_user_source_controls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "practice_answers",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("practice_answers", "version")
