from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.retrieval.segment_service import SegmentService
from app.services.segment_service import SegmentService as LegacySegmentService


def test_legacy_segment_service_exports_retrieval_implementation():
    assert LegacySegmentService is SegmentService


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
async def test_store_segments_cleans_old_vectors_only_after_mysql_commit(monkeypatch):
    events = []
    db = SimpleNamespace(
        add_all=Mock(side_effect=lambda _segments: events.append("add_all")),
        commit=AsyncMock(side_effect=lambda: events.append("commit")),
        rollback=AsyncMock(),
    )
    service = SegmentService(db)
    service.qdrant = SimpleNamespace(
        upsert_points=Mock(
            side_effect=lambda _collection, _points: events.append("upsert")
        ),
    )

    async def get_old_segments(_entity_type, _entity_ids):
        return [SimpleNamespace(qdrant_point_id="old-point")]

    async def delete_rows(_entity_type, _entity_ids):
        events.append("delete_rows")

    def delete_points(_collection, point_ids):
        events.append(("delete_points", point_ids))

    monkeypatch.setattr(service, "_get_entity_segments", get_old_segments)
    monkeypatch.setattr(service, "_delete_segment_rows", delete_rows)
    monkeypatch.setattr(service, "_delete_qdrant_points", delete_points)

    warning = await service._store_segments(
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
    service = SegmentService(db)
    service.qdrant = SimpleNamespace(upsert_points=Mock())

    async def get_old_segments(_entity_type, _entity_ids):
        return [SimpleNamespace(qdrant_point_id="old-point")]

    async def delete_rows(_entity_type, _entity_ids):
        return None

    def delete_points(_collection, point_ids):
        deleted_point_ids.append(point_ids)

    monkeypatch.setattr(service, "_get_entity_segments", get_old_segments)
    monkeypatch.setattr(service, "_delete_segment_rows", delete_rows)
    monkeypatch.setattr(service, "_delete_qdrant_points", delete_points)

    with pytest.raises(RuntimeError, match="mysql unavailable"):
        await service._store_segments(
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
    service = SegmentService(db)

    async def get_old_segments(_entity_type, _entity_ids):
        return [SimpleNamespace(qdrant_point_id="old-point")]

    async def delete_rows(_entity_type, _entity_ids):
        events.append("delete_rows")

    def delete_points(_collection, point_ids):
        events.append(("delete_points", point_ids))

    monkeypatch.setattr(service, "_get_entity_segments", get_old_segments)
    monkeypatch.setattr(service, "_delete_segment_rows", delete_rows)
    monkeypatch.setattr(service, "_delete_qdrant_points", delete_points)

    result = await service.commit_entity_segment_removal(
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
    service = SegmentService(db)

    async def get_old_segments(_entity_type, _entity_ids):
        return [SimpleNamespace(qdrant_point_id="old-point")]

    async def delete_rows(_entity_type, _entity_ids):
        return None

    def delete_points(_collection, point_ids):
        deleted_point_ids.append(point_ids)

    monkeypatch.setattr(service, "_get_entity_segments", get_old_segments)
    monkeypatch.setattr(service, "_delete_segment_rows", delete_rows)
    monkeypatch.setattr(service, "_delete_qdrant_points", delete_points)

    with pytest.raises(RuntimeError, match="mysql unavailable"):
        await service.commit_entity_segment_removal(
            "knowledge_point",
            ["knowledge-1"],
        )

    assert deleted_point_ids == []
    db.rollback.assert_awaited_once()
