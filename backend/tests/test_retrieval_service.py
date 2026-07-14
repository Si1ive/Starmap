"""Retrieval filter consistency tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import mysql

from app.db.qdrant import qdrant_manager
from app.modules.retrieval.service import RetrievalService


@pytest.mark.asyncio
async def test_sparse_search_applies_structured_filters_before_limit():
    db_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: []),
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=db_result))
    service = RetrievalService(db)

    await service._sparse_search(
        qdrant_manager.COLLECTION_QUESTION_SEGMENTS,
        "进程 调度",
        20,
        subject_id="subject-os",
        chapter_ids=["chapter-process"],
        filters={
            "exam_year": 2024,
            "exam_scope": "408",
            "difficulty": "hard",
            "question_type": "choice",
            "answer_source": "extracted",
            "tags": ["真题", "进程"],
        },
    )

    statement = db.execute.await_args.args[0]
    compiled = statement.compile(dialect=mysql.dialect())
    sql = str(compiled).lower()
    params = compiled.params

    assert "retrieval_segments.subject_id = %s" in sql
    assert sql.count("json_overlaps") == 2
    assert sql.count("json_extract") == 6
    assert "retrieval_segments.sparse_text" in sql
    assert "limit %s" in sql
    assert "subject-os" in params.values()
    assert '["chapter-process"]' in params.values()
    assert "2024" in params.values()
    assert "choice" in params.values()


@pytest.mark.asyncio
async def test_sparse_search_without_filters_keeps_keyword_only_query():
    db_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: []),
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=db_result))
    service = RetrievalService(db)

    await service._sparse_search(
        qdrant_manager.COLLECTION_KNOWLEDGE_SEGMENTS,
        "二叉树",
        10,
    )

    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=mysql.dialect())).lower()

    assert "retrieval_segments.entity_type = %s" in sql
    assert "retrieval_segments.sparse_text" in sql
    assert "json_overlaps" not in sql
    assert "json_extract" not in sql
