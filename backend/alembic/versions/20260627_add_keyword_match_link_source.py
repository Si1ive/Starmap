"""add_keyword_match_link_source

Revision ID: 20260627_keyword_match_source
Revises: 20260627_source_section_path
Create Date: 2026-06-27 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '20260627_keyword_match_source'
down_revision: Union[str, Sequence[str], None] = '20260627_source_section_path'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SOURCE_ENUM_WITH_KEYWORD = "ENUM('existing','document_mapping','vector_search','keyword_match','manual')"
SOURCE_ENUM_WITHOUT_KEYWORD = "ENUM('existing','document_mapping','vector_search','manual')"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE knowledge_point_chapter_links MODIFY COLUMN source "
        f"{SOURCE_ENUM_WITH_KEYWORD} NOT NULL DEFAULT 'manual' COMMENT '关联来源'"
    )
    op.execute(
        f"ALTER TABLE question_chapter_links MODIFY COLUMN source "
        f"{SOURCE_ENUM_WITH_KEYWORD} NOT NULL DEFAULT 'manual' COMMENT '关联来源'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE knowledge_point_chapter_links SET source = 'manual' WHERE source = 'keyword_match'"
    )
    op.execute(
        "UPDATE question_chapter_links SET source = 'manual' WHERE source = 'keyword_match'"
    )
    op.execute(
        f"ALTER TABLE question_chapter_links MODIFY COLUMN source "
        f"{SOURCE_ENUM_WITHOUT_KEYWORD} NOT NULL DEFAULT 'manual' COMMENT '关联来源'"
    )
    op.execute(
        f"ALTER TABLE knowledge_point_chapter_links MODIFY COLUMN source "
        f"{SOURCE_ENUM_WITHOUT_KEYWORD} NOT NULL DEFAULT 'manual' COMMENT '关联来源'"
    )
