"""add error_detail to downloaded_files

Revision ID: a1b2c3d4e5f6
Revises: 0a946c4cac4a
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "0a946c4cac4a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "downloaded_files",
        sa.Column("error_detail", sa.Text(), nullable=True, comment="失败原因"),
    )


def downgrade() -> None:
    op.drop_column("downloaded_files", "error_detail")
