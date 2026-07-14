from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.retrieval.relation_expansion import RetrievalRelationExpander
from app.modules.retrieval.search_engine import RetrievalResult
from app.modules.retrieval.service import RetrievalService


def _result(entity_id: str) -> RetrievalResult:
    return RetrievalResult(
        segment_id=f"segment-{entity_id}",
        entity_type="knowledge_point",
        entity_id=entity_id,
        segment_type="content",
        content_text=f"知识点 {entity_id}",
        context_text=None,
        score=0.8,
    )


@pytest.mark.asyncio
async def test_relation_expander_deduplicates_and_excludes_primary_ids(
    monkeypatch,
):
    expander = RetrievalRelationExpander(None)
    relations = [
        {
            "relation_id": "relation-1",
            "related_knowledge_id": "knowledge-2",
        },
        {
            "relation_id": "relation-2",
            "related_knowledge_id": "knowledge-2",
        },
        {
            "relation_id": "relation-3",
            "related_knowledge_id": "knowledge-1",
        },
    ]
    get_relations = AsyncMock(return_value=relations)
    get_related_results = AsyncMock(return_value=[_result("knowledge-2")])
    get_linked_questions = AsyncMock(return_value=[])
    monkeypatch.setattr(expander, "_get_relations", get_relations)
    monkeypatch.setattr(expander, "_get_related_results", get_related_results)
    monkeypatch.setattr(expander, "_get_linked_questions", get_linked_questions)

    result = await expander.expand(["knowledge-1"], limit=5)

    get_related_results.assert_awaited_once_with(["knowledge-2"], 5)
    assert result["related_results"][0]["entity_id"] == "knowledge-2"
    assert result["relations"] == relations


@pytest.mark.asyncio
async def test_linked_questions_are_deduplicated_and_limited():
    question_1 = SimpleNamespace(
        id="question-1",
        content="题目一",
        question_no="1",
        exam_year=2024,
        source="试卷",
    )
    question_2 = SimpleNamespace(
        id="question-2",
        content="题目二",
        question_no="2",
        exam_year=2023,
        source="试卷",
    )
    rows = [
        (
            SimpleNamespace(
                relevance=0.9,
                knowledge_point_id="knowledge-1",
            ),
            question_1,
        ),
        (
            SimpleNamespace(
                relevance=0.8,
                knowledge_point_id="knowledge-2",
            ),
            question_1,
        ),
        (
            SimpleNamespace(
                relevance=0.7,
                knowledge_point_id="knowledge-1",
            ),
            question_2,
        ),
    ]
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(all=lambda: rows),
        )
    )

    result = await RetrievalRelationExpander(db)._get_linked_questions(
        ["knowledge-1", "knowledge-2"],
        limit=2,
    )

    assert [item["question_id"] for item in result] == [
        "question-1",
        "question-2",
    ]
    assert result[0]["relevance"] == 0.9
    assert result[0]["via_knowledge_point_id"] == "knowledge-1"


@pytest.mark.asyncio
async def test_retrieval_service_delegates_relation_expansion(monkeypatch):
    primary = [_result("knowledge-1"), _result("knowledge-1")]
    service = RetrievalService(None)
    search = AsyncMock(return_value=primary)
    expand = AsyncMock(
        return_value={
            "related_results": [],
            "relations": [],
            "linked_questions": [],
        }
    )
    monkeypatch.setattr(service, "search", search)
    service.relation_expander = SimpleNamespace(expand=expand)

    result = await service.search_with_relations("进程调度", limit=3)

    expand.assert_awaited_once_with(["knowledge-1"], 3)
    assert len(result["primary_results"]) == 2
    assert result["linked_questions"] == []
