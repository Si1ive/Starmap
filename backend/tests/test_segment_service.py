from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.retrieval.segment_service import SegmentService
from app.modules.retrieval.segment_store import SegmentStore


@pytest.mark.asyncio
async def test_build_document_segments_initializes_collections_and_scopes_work(
    monkeypatch,
):
    service = SegmentService(None)
    service.qdrant = SimpleNamespace(init_default_collections=Mock())
    service.embedding = SimpleNamespace(dimension=1024)
    calls = []

    async def fake_build_knowledge_segments(**kwargs):
        calls.append(("knowledge", kwargs))
        return {"segments_count": 4}

    async def fake_build_question_segments(**kwargs):
        calls.append(("question", kwargs))
        return {"segments_count": 6}

    monkeypatch.setattr(
        service,
        "build_knowledge_segments",
        fake_build_knowledge_segments,
    )
    monkeypatch.setattr(
        service,
        "build_question_segments",
        fake_build_question_segments,
    )

    result = await service.build_document_segments(
        document_id="doc-1",
        include_knowledge=True,
        include_questions=False,
    )

    service.qdrant.init_default_collections.assert_called_once_with(vector_size=1024)
    assert calls == [
        ("knowledge", {"document_id": "doc-1", "rebuild": True}),
    ]
    assert result == {
        "knowledge_segments": {"segments_count": 4},
        "question_segments": {"segments_count": 0, "skipped": True},
    }


@pytest.mark.asyncio
async def test_build_canonical_chapter_segments_uses_segment_store():
    chapter = SimpleNamespace(
        id="chapter-1",
        name="数据结构",
        keywords=[],
        aliases=[],
        enhanced_description=None,
        description=None,
        level=1,
        outline_code="1",
        subject_id="subject-1",
    )
    query_result = SimpleNamespace(
        scalars=Mock(
            return_value=SimpleNamespace(
                all=Mock(return_value=[chapter]),
            )
        )
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=query_result))
    service = SegmentService(db)
    service.embedding = SimpleNamespace(
        embed_batch=AsyncMock(return_value=[[0.1, 0.2]]),
    )
    store_segments = AsyncMock(return_value=None)
    service.segment_store = SimpleNamespace(store_segments=store_segments)

    result = await service.build_canonical_chapter_segments(rebuild=True)

    assert result == {"segments_count": 1, "chapters_count": 1}
    store_segments.assert_awaited_once()
    call = store_segments.await_args.kwargs
    assert call["entity_type"] == "canonical_chapter"
    assert call["entity_ids"] == ["chapter-1"]
    assert call["rebuild"] is True
    assert len(call["segments"]) == 1
    assert len(call["qdrant_points"]) == 1


@pytest.mark.asyncio
async def test_store_segments_cleans_old_vectors_only_after_mysql_commit(monkeypatch):
    events = []
    db = SimpleNamespace(
        add_all=Mock(side_effect=lambda _segments: events.append("add_all")),
        commit=AsyncMock(side_effect=lambda: events.append("commit")),
        rollback=AsyncMock(),
    )
    store = SegmentStore(
        db,
        SimpleNamespace(
            upsert_points=Mock(
                side_effect=lambda _collection, _points: events.append("upsert")
            ),
        ),
    )

    async def get_old_segments(_entity_type, _entity_ids):
        return [SimpleNamespace(qdrant_point_id="old-point")]

    async def delete_rows(_entity_type, _entity_ids):
        events.append("delete_rows")

    def delete_points(_collection, point_ids):
        events.append(("delete_points", point_ids))

    monkeypatch.setattr(store, "_get_entity_segments", get_old_segments)
    monkeypatch.setattr(store, "_delete_segment_rows", delete_rows)
    monkeypatch.setattr(store, "_delete_qdrant_points", delete_points)

    warning = await store.store_segments(
        entity_type="question",
        entity_ids=["question-1"],
        collection="question_segments",
        segments=[SimpleNamespace(id="new-segment")],
        qdrant_points=[SimpleNamespace(id="new-point")],
        rebuild=True,
    )

    assert warning is None
    assert events == [
        "upsert",
        "delete_rows",
        "add_all",
        "commit",
        ("delete_points", ["old-point"]),
    ]
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_store_segments_commit_failure_keeps_old_vector_and_cleans_new(
    monkeypatch,
):
    deleted_point_ids = []
    db = SimpleNamespace(
        add_all=Mock(),
        commit=AsyncMock(side_effect=RuntimeError("mysql unavailable")),
        rollback=AsyncMock(),
    )
    store = SegmentStore(
        db,
        SimpleNamespace(upsert_points=Mock()),
    )

    async def get_old_segments(_entity_type, _entity_ids):
        return [SimpleNamespace(qdrant_point_id="old-point")]

    async def delete_rows(_entity_type, _entity_ids):
        return None

    def delete_points(_collection, point_ids):
        deleted_point_ids.append(point_ids)

    monkeypatch.setattr(store, "_get_entity_segments", get_old_segments)
    monkeypatch.setattr(store, "_delete_segment_rows", delete_rows)
    monkeypatch.setattr(store, "_delete_qdrant_points", delete_points)

    with pytest.raises(RuntimeError, match="mysql unavailable"):
        await store.store_segments(
            entity_type="knowledge_point",
            entity_ids=["knowledge-1"],
            collection="knowledge_segments",
            segments=[SimpleNamespace(id="new-segment")],
            qdrant_points=[SimpleNamespace(id="new-point")],
            rebuild=True,
        )

    assert deleted_point_ids == [["new-point"]]
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_commit_entity_segment_removal_cleans_qdrant_after_commit(monkeypatch):
    events = []
    db = SimpleNamespace(
        commit=AsyncMock(side_effect=lambda: events.append("commit")),
        rollback=AsyncMock(),
    )
    store = SegmentStore(db)

    async def get_old_segments(_entity_type, _entity_ids):
        return [SimpleNamespace(qdrant_point_id="old-point")]

    async def delete_rows(_entity_type, _entity_ids):
        events.append("delete_rows")

    def delete_points(_collection, point_ids):
        events.append(("delete_points", point_ids))

    monkeypatch.setattr(store, "_get_entity_segments", get_old_segments)
    monkeypatch.setattr(store, "_delete_segment_rows", delete_rows)
    monkeypatch.setattr(store, "_delete_qdrant_points", delete_points)

    result = await store.commit_entity_segment_removal(
        "question",
        ["question-1"],
    )

    assert result == {"status": "success", "segments_count": 1}
    assert events == [
        "delete_rows",
        "commit",
        ("delete_points", ["old-point"]),
    ]
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_commit_entity_segment_removal_keeps_qdrant_when_commit_fails(
    monkeypatch,
):
    deleted_point_ids = []
    db = SimpleNamespace(
        commit=AsyncMock(side_effect=RuntimeError("mysql unavailable")),
        rollback=AsyncMock(),
    )
    store = SegmentStore(db)

    async def get_old_segments(_entity_type, _entity_ids):
        return [SimpleNamespace(qdrant_point_id="old-point")]

    async def delete_rows(_entity_type, _entity_ids):
        return None

    def delete_points(_collection, point_ids):
        deleted_point_ids.append(point_ids)

    monkeypatch.setattr(store, "_get_entity_segments", get_old_segments)
    monkeypatch.setattr(store, "_delete_segment_rows", delete_rows)
    monkeypatch.setattr(store, "_delete_qdrant_points", delete_points)

    with pytest.raises(RuntimeError, match="mysql unavailable"):
        await store.commit_entity_segment_removal(
            "knowledge_point",
            ["knowledge-1"],
        )

    assert deleted_point_ids == []
    db.rollback.assert_awaited_once()
