"""Agent Worker 等待状态分类测试。"""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.models import (
    AgentApproval,
    AgentArtifact,
    AgentCheckpoint,
    AgentEvent,
    AgentInput,
    AgentMessage,
    AgentRun,
    AgentRunOutbox,
    AgentStep,
    AgentThread,
    AgentThreadEvent,
    AgentThreadItem,
)
from app.modules.agent.worker import AgentWorker
from app.modules.agent.workflows.contracts import NodeResult, WorkflowDefinition
from app.modules.agent.workflows.engine import WorkflowEngine
from app.modules.agent.workflows.registry import workflow_registry


WORKER_TABLES = [
    AgentThread.__table__,
    AgentRun.__table__,
    AgentMessage.__table__,
    AgentThreadItem.__table__,
    AgentThreadEvent.__table__,
    AgentStep.__table__,
    AgentEvent.__table__,
    AgentRunOutbox.__table__,
    AgentCheckpoint.__table__,
    AgentArtifact.__table__,
    AgentInput.__table__,
    AgentApproval.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=WORKER_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("waiting_output", "expected_status", "expected_reason"),
    [
        (
            {"waiting_for_user": True},
            "waiting_for_user",
            "等待用户补充信息",
        ),
        (
            {"waiting_for_approval": True},
            "waiting_for_approval",
            "等待用户审批",
        ),
    ],
)
async def test_worker_classifies_waiting_result_and_emits_status_event(
    db_session,
    monkeypatch,
    waiting_output,
    expected_status,
    expected_reason,
):
    thread = AgentThread(
        id="thread_001",
        user_id="user_001",
        title="会话",
        status="active",
    )
    run = AgentRun(
        id="run_001",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="waiting_test",
        workflow_key="waiting_test",
        workflow_version="v1",
        status="queued",
        presentation="workflow",
        public_title="等待状态测试",
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    run.root_run_id = run.id

    workflow = WorkflowDefinition(
        name="waiting_test",
        version="v1",
        entry_node="wait",
    )

    async def execute_waiting(self, workflow_definition, context, current_run, resume_from=None):
        return NodeResult.waiting(output=waiting_output)

    monkeypatch.setattr(workflow_registry, "get", lambda name: workflow)
    monkeypatch.setattr(WorkflowEngine, "execute", execute_waiting)

    assert await AgentWorker().process_run(db_session, run) is True
    assert run.status == expected_status

    events = list(
        (
            await db_session.execute(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.id)
                .order_by(AgentEvent.sequence)
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == [
        "run.status_changed",
        "run.status_changed",
    ]
    assert events[-1].payload == {
        "from": "running",
        "to": expected_status,
        "reason": expected_reason,
    }

    thread_events = list(
        (
            await db_session.execute(
                select(AgentThreadEvent).order_by(AgentThreadEvent.sequence)
            )
        )
        .scalars()
        .all()
    )
    assert thread_events[-1].event_type == "workflow.updated"
    assert thread_events[-1].payload["status"] == expected_status
    assert thread_events[-1].payload["reason"] == expected_reason
