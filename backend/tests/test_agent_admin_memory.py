"""管理员 Run/Snapshot/source 记忆观测契约测试。"""

from datetime import timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.admin_memory import (
    get_run_memory_observability,
    get_snapshot_item_source,
    redact_admin_value,
    replay_run_memory_snapshot,
)
from app.modules.agent.models import (
    AgentConversationSummary,
    AgentEvent,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentMemoryUpdateOutbox,
    AgentMessage,
    AgentRun,
    AgentThread,
)
from app.modules.agent.time_utils import utc_now


ADMIN_MEMORY_TABLES = [
    AgentThread.__table__,
    AgentMessage.__table__,
    AgentRun.__table__,
    AgentEvent.__table__,
    AgentMemorySnapshot.__table__,
    AgentMemorySnapshotItem.__table__,
    AgentConversationSummary.__table__,
    AgentMemoryUpdateOutbox.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=ADMIN_MEMORY_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _seed_snapshot(db_session):
    now = utc_now()
    thread = AgentThread(
        id="thread_admin_memory_001",
        user_id="user_admin_memory_001",
        title="记忆观测",
        status="active",
    )
    run = AgentRun(
        id="run_admin_memory_001",
        thread_id=thread.id,
        user_id=thread.user_id,
        workflow_name="conversation",
        workflow_key="conversation",
        workflow_version="v1",
        status="completed",
        input_message="继续讲二分查找",
        model_call_count=2,
        max_model_calls=3,
        metadata_json={
            "model_config_id": "model-safe",
            "model_name": "glm-safe",
            "model_provider": "openai_compatible",
            "model_calls": [
                {"id": "model_call_first", "model_name": "glm-safe"},
                {"id": "model_call_final", "model_name": "glm-safe"},
            ],
            "context_audit": {"token_budget": 1800, "estimated_tokens": 320},
        },
    )
    message = AgentMessage(
        id="message_admin_memory_001",
        thread_id=thread.id,
        user_id=thread.user_id,
        run_id=run.id,
        role="user",
        status="completed",
        content_text="继续讲二分查找",
    )
    summary = AgentConversationSummary(
        id="summary_admin_memory_001",
        thread_id=thread.id,
        user_id=thread.user_id,
        start_sequence=1,
        end_sequence=4,
        summary_text="用户正在学习二分查找。",
        source_message_ids_json=[message.id],
        version=2,
        superseded_by_id=None,
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    db_session.add_all([message, summary])
    await db_session.flush()
    snapshot = AgentMemorySnapshot(
        id="memsnap_admin_memory_001",
        run_id=run.id,
        thread_id=thread.id,
        user_id=thread.user_id,
        state_version=7,
        standalone_request="讲解二分查找",
        understanding_json={
            "raw_input": "继续讲二分查找",
            "standalone_request": "讲解二分查找",
            "topic_entities": [{"title": "二分查找", "source": "thread_memory"}],
            "constraints": [],
            "reference_sources": [],
        },
        selection_metadata_json={"conversation_summary_id": summary.id},
    )
    db_session.add(snapshot)
    await db_session.flush()
    item = AgentMemorySnapshotItem(
        snapshot_id=snapshot.id,
        memory_need="conversation_continuity",
        memory_partition="historical_summaries",
        source_kind="conversation_summary",
        source_id=summary.id,
        item_key=summary.id,
        version=summary.version,
        selected=True,
        selection_reason="active_summary_before_recent_history",
        token_estimate=42,
        payload_json={
            "summary_text": "冻结摘要正文",
            "api_key": "must-not-leak",
        },
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add_all(
        [
            AgentEvent(
                run_id=run.id,
                sequence=1,
                event_type="tool.called",
                payload={
                    "activity_id": "activity-1",
                    "attempt_id": "attempt-1",
                    "public_metadata": {
                        "tool": "retrieve_knowledge",
                        "query": "二分查找",
                        "entity_type": "knowledge_point",
                        "chapter_ids": ["chapter-1"],
                        "exclude_entity_ids": ["question-9"],
                        "filters": {"difficulty": "hard"},
                        "authorization": "Bearer should-not-leak",
                    },
                },
                created_at=now,
            ),
            AgentMemoryUpdateOutbox(
                run_id=run.id,
                thread_id=thread.id,
                user_id=thread.user_id,
                event_type="conversation_summary_maintenance",
                status="completed",
                payload_json={"task_type": "conversation_summary_maintenance"},
                scheduled_at=now,
                processed_at=now + timedelta(seconds=1),
            ),
        ]
    )
    await db_session.flush()
    return run, snapshot, item, summary


@pytest.mark.asyncio
async def test_run_memory_observability_uses_frozen_snapshot_and_actual_tool_event(
    db_session,
):
    run, snapshot, item, _summary = await _seed_snapshot(db_session)

    payload = await get_run_memory_observability(db_session, run.id)

    assert payload["snapshot"]["id"] == snapshot.id
    assert payload["snapshot"]["state_version"] == 7
    assert payload["items"][0]["id"] == item.id
    assert payload["items"][0]["frozen_payload"]["summary_text"] == "冻结摘要正文"
    assert payload["items"][0]["frozen_payload"]["api_key"] == "[REDACTED]"
    assert payload["token_budget"] == {
        "configured": 1800,
        "context_estimated": 320,
        "selected_items": 42,
        "dropped_items": 0,
    }
    assert payload["model"]["final_model_call_id"] == "model_call_final"
    assert payload["tool_calls"][0]["query"] == "二分查找"
    assert payload["tool_calls"][0]["difficulty"] == "hard"
    assert payload["tool_calls"][0]["exclude_entity_ids"] == ["question-9"]
    assert "authorization" not in payload["tool_calls"][0]
    assert payload["memory_outbox"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_snapshot_replay_is_read_only_and_keeps_original_item_order(db_session):
    run, _snapshot, item, _summary = await _seed_snapshot(db_session)
    before = await db_session.scalar(select(func.count(AgentMemorySnapshotItem.id)))

    payload = await replay_run_memory_snapshot(db_session, run.id)

    after = await db_session.scalar(select(func.count(AgentMemorySnapshotItem.id)))
    assert payload["mode"] == "frozen_snapshot_read_only"
    assert [row["id"] for row in payload["ordered_items"]] == [item.id]
    assert payload["actual_tool_calls"][0]["attempt_id"] == "attempt-1"
    assert before == after == 1


@pytest.mark.asyncio
async def test_child_run_observability_uses_its_bound_parent_snapshot(db_session):
    parent, snapshot, _item, _summary = await _seed_snapshot(db_session)
    child = AgentRun(
        id="run_admin_memory_child_001",
        thread_id=parent.thread_id,
        user_id=parent.user_id,
        workflow_name="explain",
        workflow_key="explain",
        workflow_version="v1",
        status="completed",
        parent_run_id=parent.id,
        root_run_id=parent.id,
        metadata_json={"memory_snapshot_id": snapshot.id},
    )
    db_session.add(child)
    await db_session.flush()

    payload = await get_run_memory_observability(db_session, child.id)

    assert payload["run"]["id"] == child.id
    assert payload["snapshot"]["id"] == snapshot.id
    assert payload["items"][0]["frozen_payload"]["summary_text"] == "冻结摘要正文"


@pytest.mark.asyncio
async def test_source_lookup_separates_frozen_copy_and_superseded_current_source(
    db_session,
):
    run, _snapshot, item, summary = await _seed_snapshot(db_session)
    summary.superseded_by_id = "summary_newer_001"

    payload = await get_snapshot_item_source(
        db_session,
        run_id=run.id,
        item_id=item.id,
    )

    assert payload["frozen_copy"]["summary_text"] == "冻结摘要正文"
    assert payload["current_source"]["summary_text"] == "用户正在学习二分查找。"
    assert payload["frozen_version"] == payload["current_version"] == 2
    assert payload["superseded"] is True


@pytest.mark.asyncio
async def test_source_lookup_hides_cross_run_and_version_mismatch_as_same_404(db_session):
    run, _snapshot, item, summary = await _seed_snapshot(db_session)

    with pytest.raises(HTTPException) as cross_run:
        await get_snapshot_item_source(
            db_session,
            run_id="run_from_another_scope",
            item_id=item.id,
        )

    summary.version = 3
    with pytest.raises(HTTPException) as changed_version:
        await get_snapshot_item_source(
            db_session,
            run_id=run.id,
            item_id=item.id,
        )

    assert cross_run.value.status_code == changed_version.value.status_code == 404
    assert cross_run.value.detail == changed_version.value.detail == "记忆来源不存在"


def test_admin_redaction_covers_nested_credentials_without_hiding_token_estimates():
    payload = redact_admin_value(
        {
            "token_estimate": 12,
            "api_key": "secret",
            "nested": {
                "authorization": "Bearer abc.def",
                "dsn_text": "mysql://root:password@db.internal/app",
            },
        }
    )

    assert payload["token_estimate"] == 12
    assert payload["api_key"] == "[REDACTED]"
    assert payload["nested"]["authorization"] == "[REDACTED]"
    assert payload["nested"]["dsn_text"] == "mysql://[REDACTED]@db.internal/app"
