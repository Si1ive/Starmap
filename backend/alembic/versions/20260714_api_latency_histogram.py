"""Add mergeable API latency histograms.

Revision ID: 20260714_api_latency_histogram
Revises: 20260714_review_decoupled
Create Date: 2026-07-14 03:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260714_api_latency_histogram"
down_revision: Union[str, Sequence[str], None] = "20260714_review_decoupled"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"] for column in inspector.get_columns("api_call_stats")
    }
    if "latency_histogram" not in columns:
        op.add_column(
            "api_call_stats",
            sa.Column(
                "latency_histogram",
                sa.JSON(),
                nullable=True,
                comment="可合并的固定桶延迟直方图",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"] for column in inspector.get_columns("api_call_stats")
    }
    if "latency_histogram" in columns:
        op.drop_column("api_call_stats", "latency_histogram")
