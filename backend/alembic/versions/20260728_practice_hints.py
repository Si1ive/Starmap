"""record layered hint use in practice answers

Revision ID: 20260728_practice_hints
Revises: 20260728_practice_answer_version
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_practice_hints"
down_revision: Union[str, Sequence[str], None] = "20260728_practice_answer_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "practice_answers",
        sa.Column("hint_levels_used_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("practice_answers", "hint_levels_used_json")
