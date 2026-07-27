"""管理员 Memory Outbox 筛选、详情、审计与幂等重放测试。"""

from datetime import timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.models.mysql_models import AuditLog
from app.modules.agent.admin_memory_outbox import (
    get_memory_outbox_detail,
    list_memory_outbox,
    replay_memory_outbox,
)
from app.modules.agent.models import (
    AgentMemoryUpdateOutbox,
    AgentMessage,
    AgentRun,
    AgentThread,
)
from app.modules.agent.time_utils import utc_now


ADMIN_OUTBOX_TABLES = [
    AgentThread.__table__,
    AgentMessage.__table__,
    AgentRun.__table__,
    AgentMemoryUpdateOutbox.__table__,
    AuditLog.__table__,
]
AuditLog.__table__.c.id.type = AuditLog.__table__.c.id.type.with_variant(
    Integer(),
    "sqlite",
)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=ADMIN_OUTBOX_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _seed_outbox(
    db_session,
    *,
    outbox_id: int,
    status: str = "failed",
    scheduled_offset_seconds: int = -60,
):
    thread_id = f"thread_admin_outbox_{outbox_id:03d}"
    run_id = f"run_admin_outbox_{outbox_id:03d}"
    thread = AgentThread(
        id=thread_id,
        user_id="user_admin_outbox",
        title="Outbox 运维",
        status="active",
    )
    run = AgentRun(
        id=run_id,
        thread_id=thread_id,
        user_id=thread.user_id,
        workflow_name="conversation",
        workflow_key="conversation",
        workflow_version="v1",
        status="completed",
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    now = utc_now()
    row = AgentMemoryUpdateOutbox(
        id=outbox_id,
        run_id=run.id,
        thread_id=thread.id,
        user_id=thread.user_id,
        event_type="topic_confirmed" if outbox_id == 1 else "memory_vector_upsert",
        task_key=None,
        status=status,
        payload_json={
            "memory_event_id": 42 if outbox_id == 1 else 84,
            "source_id": "source-secret" if outbox_id == 1 else "source-other",
            "api_key": "must-not-leak",
        },
        retry_count=3,
        worker_id="memory-worker-old" if status in {"failed", "processing"} else None,
        last_error_message="Bearer private-token failed at mysql://root:pass@db/app",
        scheduled_at=now + timedelta(seconds=scheduled_offset_seconds),
        processed_at=now if status == "failed" else None,
        created_at=now - timedelta(minutes=outbox_id),
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_outbox_list_filters_failed_event_and_exact_source_id(db_session):
    failed = await _seed_outbox(db_session, outbox_id=1)
    await _seed_outbox(db_session, outbox_id=2, status="completed")

    payload = await list_memory_outbox(
        db_session,
        page=1,
        page_size=20,
        event_type="topic_confirmed",
        status="failed",
        run_id=failed.run_id,
        thread_id=failed.thread_id,
        source_id="42",
    )

    assert payload["total"] == 1
    assert [row["id"] for row in payload["items"]] == [failed.id]
    assert payload["items"][0]["safe_error_summary"] == (
        "Bearer [REDACTED] failed at mysql://[REDACTED]@db/app"
    )
    assert payload["items"][0]["replay_allowed"] is True


@pytest.mark.asyncio
async def test_outbox_detail_returns_redacted_payload_and_failure_summary(db_session):
    row = await _seed_outbox(db_session, outbox_id=1)

    payload = await get_memory_outbox_detail(db_session, row.id)

    assert payload["payload"]["source_id"] == "source-secret"
    assert payload["payload"]["api_key"] == "[REDACTED]"
    assert "private-token" not in payload["safe_error_summary"]


@pytest.mark.asyncio
async def test_replay_reuses_original_row_and_records_admin_audit(db_session):
    row = await _seed_outbox(db_session, outbox_id=1)
    original_run_id = row.run_id
    original_event_type = row.event_type

    first = await replay_memory_outbox(
        db_session,
        outbox_id=row.id,
        admin_user_id="admin-operator-1",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    second = await replay_memory_outbox(
        db_session,
        outbox_id=row.id,
        admin_user_id="admin-operator-1",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    await db_session.refresh(row)
    assert first["id"] == second["id"] == row.id
    assert row.status == "pending"
    assert row.retry_count == 0
    assert row.worker_id is None
    assert row.processed_at is None
    assert row.run_id == original_run_id
    assert row.event_type == original_event_type
    assert await db_session.scalar(select(func.count(AgentMemoryUpdateOutbox.id))) == 1
    audits = list(
        (
            await db_session.execute(
                select(AuditLog).order_by(AuditLog.id)
            )
        ).scalars()
    )
    assert len(audits) == 2
    assert {audit.action for audit in audits} == {"agent_memory_outbox_replay"}
    assert audits[0].user_id == "admin-operator-1"
    assert audits[0].resource_id == str(row.id)
    assert audits[0].new_values["run_id"] == original_run_id


@pytest.mark.asyncio
async def test_replay_rejects_completed_and_active_processing_lease(db_session):
    completed = await _seed_outbox(db_session, outbox_id=1, status="completed")
    processing = await _seed_outbox(
        db_session,
        outbox_id=2,
        status="processing",
        scheduled_offset_seconds=300,
    )

    for row in (completed, processing):
        with pytest.raises(HTTPException) as error:
            await replay_memory_outbox(
                db_session,
                outbox_id=row.id,
                admin_user_id="admin-operator-1",
                ip_address=None,
                user_agent=None,
            )
        assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_replay_recovers_expired_processing_lease(db_session):
    row = await _seed_outbox(
        db_session,
        outbox_id=1,
        status="processing",
        scheduled_offset_seconds=-1,
    )

    payload = await replay_memory_outbox(
        db_session,
        outbox_id=row.id,
        admin_user_id="admin-operator-1",
        ip_address=None,
        user_agent=None,
    )

    assert payload["status"] == "pending"
    assert payload["replay_allowed"] is True
