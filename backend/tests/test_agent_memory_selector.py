"""Memory bundle selectors for workflow consumers."""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.memory_selector import load_practice_bundle
from app.modules.agent.models import (
    AgentMessage,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentRun,
    AgentThread,
)

SELECTOR_TABLES = [
    AgentThread.__table__,
    AgentMessage.__table__,
    AgentRun.__table__,
    AgentMemorySnapshot.__table__,
    AgentMemorySnapshotItem.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=SELECTOR_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_load_practice_bundle_uses_snapshot_topic_and_context_metadata(db_session):
    thread = AgentThread(
        id="thread_001",
        user_id="user_001",
        title="练习题线程",
        status="active",
    )
    run = AgentRun(
        id="run_validate_001",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        workflow_key="validate",
        workflow_version="v1",
        status="queued",
        input_message="给我出道题",
        metadata_json={
            "memory_snapshot_id": "memsnap_001",
        },
        created_at=datetime(2026, 7, 26, 20, 0, 0),
    )
    snapshot = AgentMemorySnapshot(
        id="memsnap_001",
        run_id=run.id,
        thread_id=thread.id,
        user_id="user_001",
        state_version=4,
        standalone_request="给用户出一道关于二分查找的练习题",
        understanding_json={
            "raw_input": "给我出道题",
            "standalone_request": "给用户出一道关于二分查找的练习题",
            "intent_hint": "practice_generation",
            "topic_entities": [
                {
                    "entity_type": "knowledge_point",
                    "entity_id": "kp_binary_search",
                    "title": "二分查找",
                    "source": "thread_memory",
                    "aliases": ["折半查找"],
                }
            ],
            "constraints": ["难度适中"],
            "reference_sources": [{"type": "knowledge_point", "id": "kp_binary_search"}],
        },
        selection_metadata_json={
            "selected_message_ids": ["msg_001"],
            "selected_artifact_ids": ["artifact_001", "artifact_002"],
        },
    )
    snapshot_item = AgentMemorySnapshotItem(
        snapshot_id=snapshot.id,
        memory_need="topic_focus",
        memory_partition="current_turn_understanding",
        source_kind="message",
        source_id="msg_001",
        item_key="msg_001",
        version=4,
        selected=True,
        selection_reason="current_turn_understanding",
        token_estimate=8,
        payload_json={"title": "二分查找"},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    db_session.add(snapshot)
    await db_session.flush()
    db_session.add(snapshot_item)
    await db_session.flush()

    bundle = await load_practice_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )

    assert bundle.snapshot_id == "memsnap_001"
    assert bundle.standalone_request == "给用户出一道关于二分查找的练习题"
    assert bundle.topic is not None
    assert bundle.topic.title == "二分查找"
    assert bundle.topic.aliases == ["折半查找"]
    assert bundle.constraints == ["难度适中"]
    assert bundle.selected_artifact_ids == ["artifact_001", "artifact_002"]
