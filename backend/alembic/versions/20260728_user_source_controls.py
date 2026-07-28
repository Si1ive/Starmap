"""add private source retrieval and deletion controls

Revision ID: 20260728_user_source_controls
Revises: 20260728_practice_snapshot
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_user_source_controls"
down_revision: Union[str, Sequence[str], None] = "20260728_practice_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "corpus_files",
        sa.Column(
            "retrieval_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "corpus_files",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_corpus_files_availability",
        "corpus_files",
        ["owner_user_id", "deleted_at", "retrieval_enabled"],
    )


def downgrade() -> None:
    op.drop_index("idx_corpus_files_availability", table_name="corpus_files")
    op.drop_column("corpus_files", "deleted_at")
    op.drop_column("corpus_files", "retrieval_enabled")
