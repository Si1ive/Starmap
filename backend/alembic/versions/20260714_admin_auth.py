"""Repair the default administrator password for database authentication.

Revision ID: 20260714_admin_auth
Revises: 20260714_api_latency_histogram
Create Date: 2026-07-14 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260714_admin_auth"
down_revision: Union[str, Sequence[str], None] = "20260714_api_latency_histogram"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_INVALID_HASH = (
    "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiAYMyzJ/I1K"
)
ADMIN123_HASH = (
    "pbkdf2_sha256$260000$c3Rhcm1hcC1hZG1pbi12MQ==$"
    "C8noSgD3Ai6cTZy7F4rBuD/NQ3wGosCO8KNy/2unhKM="
)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE admin_users
            SET password_hash = :next_hash
            WHERE username = 'admin' AND password_hash = :current_hash
            """
        ).bindparams(
            next_hash=ADMIN123_HASH,
            current_hash=LEGACY_INVALID_HASH,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE admin_users
            SET password_hash = :next_hash
            WHERE username = 'admin' AND password_hash = :current_hash
            """
        ).bindparams(
            next_hash=LEGACY_INVALID_HASH,
            current_hash=ADMIN123_HASH,
        )
    )
