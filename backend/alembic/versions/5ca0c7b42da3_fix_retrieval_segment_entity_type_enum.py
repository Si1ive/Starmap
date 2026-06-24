"""fix_retrieval_segment_entity_type_enum

Revision ID: 5ca0c7b42da3
Revises: 20260621_chapter_link_fields
Create Date: 2026-06-24 02:03:21.403086

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ca0c7b42da3'
down_revision: Union[str, Sequence[str], None] = '20260621_chapter_link_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'canonical_chapter' to retrieval_segments.entity_type ENUM."""
    op.execute(
        "ALTER TABLE retrieval_segments MODIFY COLUMN entity_type "
        "ENUM('knowledge_point','question','canonical_chapter') "
        "NOT NULL COMMENT '实体类型'"
    )


def downgrade() -> None:
    """Revert entity_type ENUM to original values."""
    op.execute(
        "ALTER TABLE retrieval_segments MODIFY COLUMN entity_type "
        "ENUM('knowledge_point','question') "
        "NOT NULL COMMENT '实体类型'"
    )
