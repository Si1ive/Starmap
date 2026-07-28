"""bind personal corpus files to learning users

Revision ID: 20260728_user_private_corpus
Revises: 20260728_agent_llm_audit
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from app.db.types import UUIDBinary

revision: str = "20260728_user_private_corpus"
down_revision: Union[str, Sequence[str], None] = "20260728_agent_llm_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "corpus_files",
        sa.Column("owner_user_id", UUIDBinary(), nullable=True),
    )
    op.create_foreign_key(
        "fk_corpus_files_owner_user_id",
        "corpus_files",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uk_corpus_files_sha256", "corpus_files", type_="unique")
    op.create_index("idx_corpus_files_sha256", "corpus_files", ["sha256"])
    op.create_index(
        "idx_corpus_files_owner",
        "corpus_files",
        ["owner_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_corpus_files_owner", table_name="corpus_files")
    op.drop_index("idx_corpus_files_sha256", table_name="corpus_files")
    op.create_unique_constraint(
        "uk_corpus_files_sha256",
        "corpus_files",
        ["sha256"],
    )
    op.drop_constraint(
        "fk_corpus_files_owner_user_id",
        "corpus_files",
        type_="foreignkey",
    )
    op.drop_column("corpus_files", "owner_user_id")
