"""Retrieval filter consistency tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import mysql

from app.db.qdrant import qdrant_manager
from app.modules.retrieval import service as retrieval_service_module
from app.modules.retrieval.search_engine import RetrievalSearchEngine
from app.modules.retrieval.service import RetrievalService


def test_build_filter_keeps_qdrant_and_sparse_filter_dimensions_aligned():
    qdrant_filter = RetrievalSearchEngine.build_filter(
        subject_id="subject-os",
        chapter_ids=["chapter-process"],
        filters={
            "exam_year": 2024,
            "difficulty": "hard",
            "tags": ["真题"],
        },
        knowledge_point_ids=["kp-1"],
        exclude_entity_ids=["question-excluded"],
    )

    conditions = {condition.key: condition for condition in qdrant_filter.must}
    assert set(conditions) == {
        "subject_id",
        "chapter_ids",
        "knowledge_point_ids",
        "exam_year",
        "difficulty",
        "tags",
    }
    assert conditions["subject_id"].match.value == "subject-os"
    assert conditions["chapter_ids"].match.any == ["chapter-process"]
    assert conditions["knowledge_point_ids"].match.any == ["kp-1"]
    assert conditions["tags"].match.any == ["真题"]
    assert qdrant_filter.must_not[0].key == "entity_id"
    assert qdrant_filter.must_not[0].match.any == ["question-excluded"]


def test_merge_hits_does_not_mutate_qdrant_or_sparse_hits():
    dense_hits = [
        {"id": "shared", "score": 0.8, "payload": {"segment_id": "segment-1"}},
        {"id": "dense", "score": 0.5, "payload": {"segment_id": "segment-2"}},
    ]
    sparse_hits = [
        {"id": "shared", "score": 1.0, "payload": {"segment_id": "segment-1"}},
        {"id": "sparse", "score": 0.6, "payload": {"segment_id": "segment-3"}},
    ]

    merged = RetrievalSearchEngine.merge_hits(dense_hits, sparse_hits)

    assert [hit["id"] for hit in merged] == ["shared", "dense", "sparse"]
    assert merged[0]["score"] == pytest.approx(0.86)
    assert merged[2]["score"] == pytest.approx(0.48)
    assert dense_hits[0] == {
        "id": "shared",
        "score": 0.8,
        "payload": {"segment_id": "segment-1"},
    }
    assert sparse_hits[1]["score"] == 0.6


@pytest.mark.asyncio
async def test_outline_expansion_keeps_explicit_chapter_scope_strict(monkeypatch):
    monkeypatch.setattr(
        retrieval_service_module,
        "expand_query_with_outline",
        AsyncMock(
            return_value=SimpleNamespace(
                expanded_query="二分查找 栈",
                matched_chapters=[
                    {"chapter_id": "cchap_outline_01"},
                    {"chapter_id": "cchap_outline_02"},
                ],
                subject_ids=["subject_outline_guess"],
                chapter_ids=["cchap_outline_01", "cchap_outline_02"],
            )
        ),
    )
    service = RetrievalService(None)
    service.search = AsyncMock(return_value=[])

    await service.search_with_outline_expansion(
        query="二分查找",
        chapter_ids=["cchap_explicit_03"],
        strict_chapter_scope=True,
        entity_type="question",
    )

    assert service.search.await_args.kwargs["chapter_ids"] == [
        "cchap_explicit_03"
    ]
    assert service.search.await_args.kwargs["subject_id"] is None


@pytest.mark.asyncio
async def test_hydrate_results_preserves_hit_order_and_adds_source_display_name():
    segment = SimpleNamespace(
        id="segment-1",
        entity_type="question",
        entity_id="question-1",
        segment_type="content",
        content_text="进程调度题",
        context_text="上下文",
        subject_id="subject-os",
        chapter_ids=["chapter-process"],
        document_id="document-1",
        page_no=3,
    )
    segment_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [segment]),
    )
    document_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(
            all=lambda: [
                SimpleNamespace(
                    id="document-1",
                    source_label="2024 年 408 真题",
                    title="操作系统真题",
                ),
            ]
        ),
    )
    chapter_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(
            all=lambda: [
                SimpleNamespace(
                    id="chapter-process",
                    name="进程管理",
                    level=2,
                    code="OS-2",
                    outline_code="2.3",
                )
            ]
        ),
    )
    question_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(
            all=lambda: [
                SimpleNamespace(
                    id="question-1",
                    content="进程调度题",
                    question_no="12",
                    review_status="approved",
                    status="active",
                    type="choice",
                    difficulty="medium",
                    source="2024 年 408 真题",
                    paper_name="操作系统真题",
                    exam_year=2024,
                    exam_scope="408",
                    answer_source="extracted",
                    knowledge_point_ids=["kp-1"],
                    tags=["真题"],
                )
            ]
        ),
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[segment_result, document_result, chapter_result, question_result]
        ),
    )

    results = await RetrievalSearchEngine(db).hydrate_results(
        [
            {
                "id": "point-1",
                "score": 0.92,
                "payload": {"segment_id": "segment-1"},
            },
            {
                "id": "stale-point",
                "score": 0.8,
                "payload": {"segment_id": "missing-segment"},
            },
        ]
    )

    assert len(results) == 1
    assert results[0].segment_id == "segment-1"
    assert results[0].score == 0.92
    assert results[0].source_filename == "2024 年 408 真题"
    assert results[0].page_no == 3
    payload = results[0].to_dict()
    assert payload["entity"]["title"] == "[12] 进程调度题"
    assert payload["entity"]["review_status"] == "approved"
    assert payload["question_meta"]["question_type"] == "choice"
    assert payload["question_meta"]["paper_name"] == "操作系统真题"
    assert payload["chapters"] == [
        {
            "id": "chapter-process",
            "name": "进程管理",
            "level": 2,
            "code": "OS-2",
            "outline_code": "2.3",
        }
    ]


@pytest.mark.asyncio
async def test_hydrate_results_falls_back_to_title_and_handles_missing_source():
    segment_with_doc = SimpleNamespace(
        id="segment-1",
        entity_type="knowledge_point",
        entity_id="kp-1",
        segment_type="summary",
        content_text="二分查找要求有序。",
        context_text=None,
        subject_id="subject-ds",
        chapter_ids=["chapter-search"],
        document_id="document-1",
        page_no=1,
    )
    segment_without_doc = SimpleNamespace(
        id="segment-2",
        entity_type="knowledge_point",
        entity_id="kp-2",
        segment_type="summary",
        content_text="哈希查找依赖散列函数。",
        context_text=None,
        subject_id="subject-ds",
        chapter_ids=["chapter-search"],
        document_id=None,
        page_no=None,
    )
    segment_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(
            all=lambda: [segment_with_doc, segment_without_doc]
        ),
    )
    document_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(
            all=lambda: [
                SimpleNamespace(id="document-1", source_label=None, title="算法教材"),
            ]
        ),
    )
    chapter_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(
            all=lambda: [
                SimpleNamespace(
                    id="chapter-search",
                    name="查找算法",
                    level=3,
                    code="DS-3.1",
                    outline_code="3.1",
                )
            ]
        ),
    )
    knowledge_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(
            all=lambda: [
                SimpleNamespace(
                    id="kp-1",
                    title="二分查找",
                    review_status="approved",
                    status="active",
                    difficulty="medium",
                    exam_frequency="high",
                    source="算法教材",
                    source_page="12",
                    aliases=["折半查找"],
                    tags=["查找"],
                ),
                SimpleNamespace(
                    id="kp-2",
                    title="哈希查找",
                    review_status="approved",
                    status="active",
                    difficulty="medium",
                    exam_frequency="medium",
                    source=None,
                    source_page=None,
                    aliases=[],
                    tags=[],
                ),
            ]
        ),
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[segment_result, document_result, chapter_result, knowledge_result]
        ),
    )

    results = await RetrievalSearchEngine(db).hydrate_results(
        [
            {
                "id": "point-1",
                "score": 0.92,
                "payload": {"segment_id": "segment-1"},
            },
            {
                "id": "point-2",
                "score": 0.66,
                "payload": {"segment_id": "segment-2"},
            },
        ]
    )

    assert [result.segment_id for result in results] == ["segment-1", "segment-2"]
    assert results[0].source_filename == "算法教材"
    assert results[1].source_filename is None
    payload = results[0].to_dict()
    assert payload["knowledge_point_meta"]["difficulty"] == "medium"
    assert payload["knowledge_point_meta"]["aliases"] == ["折半查找"]
    assert payload["chapters"][0]["name"] == "查找算法"


@pytest.mark.asyncio
async def test_retrieval_service_delegates_storage_steps_to_search_engine():
    hydrated = SimpleNamespace(score=0.9)
    dense_hits = [
        {"id": "point-1", "score": 0.9, "payload": {"segment_id": "segment-1"}},
    ]
    service = RetrievalService(None)
    service.embedding = SimpleNamespace(
        embed_text=AsyncMock(return_value=[0.1, 0.2]),
    )
    service.qdrant = SimpleNamespace(search=Mock(return_value=dense_hits))
    service.search_engine = SimpleNamespace(
        build_filter=Mock(return_value=None),
        get_collections=Mock(return_value=["question_segments"]),
        sparse_search=AsyncMock(return_value=[]),
        merge_hits=Mock(return_value=dense_hits),
        hydrate_results=AsyncMock(return_value=[hydrated]),
    )

    results = await service.search(
        query="进程调度",
        entity_type="question",
        mode="hybrid",
        limit=5,
    )

    assert results == [hydrated]
    service.search_engine.merge_hits.assert_called_once_with(dense_hits, [])
    service.search_engine.hydrate_results.assert_awaited_once_with(dense_hits)


@pytest.mark.asyncio
async def test_retrieval_service_records_agent_rag_dense_qdrant_recall(monkeypatch):
    class FakeVectorRecallRecorder:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.results = None
            self.persisted = False
            self.__class__.instances.append(self)

        def start(self):
            return self

        def record_qdrant_results(self, hits, *, threshold, collection_name, **kwargs):
            self.results = {
                "hits": hits,
                "threshold": threshold,
                "collection_name": collection_name,
                **kwargs,
            }

        async def persist(self):
            self.persisted = True

    monkeypatch.setattr(
        retrieval_service_module,
        "VectorRecallRecorder",
        FakeVectorRecallRecorder,
        raising=False,
    )
    dense_hits = [
        {
            "id": "point-1",
            "score": 0.93,
            "payload": {
                "segment_id": "segment-1",
                "entity_id": "kp-1",
                "entity_type": "knowledge_point",
                "content_preview": "二分查找要求有序。",
            },
        }
    ]
    service = RetrievalService(None)
    service.embedding = SimpleNamespace(
        embed_text=AsyncMock(return_value=[0.1, 0.2]),
    )
    service.qdrant = SimpleNamespace(search=Mock(return_value=dense_hits))
    service.search_engine = SimpleNamespace(
        build_filter=Mock(return_value=None),
        get_collections=Mock(return_value=["knowledge_segments"]),
        sparse_search=AsyncMock(return_value=[]),
        merge_hits=Mock(return_value=dense_hits),
        hydrate_results=AsyncMock(return_value=[]),
    )

    await service.search(
        query="二分查找",
        entity_type="knowledge_point",
        mode="hybrid",
        limit=5,
        recall_called_by="agent_rag",
        recall_purpose="Agent RAG 内容向量召回",
    )

    recorder = FakeVectorRecallRecorder.instances[0]
    assert recorder.kwargs == {
        "called_by": "agent_rag",
        "purpose": "Agent RAG 内容向量召回",
        "query_text": "二分查找",
        "query_entity_id": None,
        "subject_id": None,
        "trace_id": None,
        "run_id": None,
        "activity_id": None,
        "attempt_id": None,
        "phase": "content_dense",
        "collection_name": "knowledge_segments",
        "query_kind": "raw",
        "raw_query_text": "二分查找",
    }
    assert recorder.results == {
        "hits": dense_hits,
        "threshold": pytest.approx(0.55),
        "collection_name": "knowledge_segments",
        "title_by_segment_id": {},
    }
    assert recorder.persisted is True


@pytest.mark.asyncio
async def test_sparse_search_applies_structured_filters_before_limit():
    db_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: []),
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=db_result))
    engine = RetrievalSearchEngine(db)

    await engine.sparse_search(
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
    engine = RetrievalSearchEngine(db)

    await engine.sparse_search(
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
