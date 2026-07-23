"""工作流引擎公开进度持久化测试。"""

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
    AgentStep,
    AgentThread,
    AgentThreadEvent,
    AgentThreadItem,
)
from app.modules.agent.timeline import AgentTimelineService
from app.modules.agent.workflows.contracts import (
    ExecutionContext,
    Node,
    NodeResult,
    WorkflowDefinition,
)
from app.modules.agent.workflows.engine import WorkflowEngine

ENGINE_TABLES = [
    AgentThread.__table__,
    AgentRun.__table__,
    AgentMessage.__table__,
    AgentThreadItem.__table__,
    AgentThreadEvent.__table__,
    AgentStep.__table__,
    AgentEvent.__table__,
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
                tables=ENGINE_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_engine_persists_public_step_for_timeline_snapshot(db_session):
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
        workflow_name="explain",
        workflow_key="explain",
        workflow_version="v1",
        status="running",
        presentation="compact",
        public_title="整理讲解",
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    run.root_run_id = run.id
    await AgentTimelineService(db_session).ensure_workflow_item(
        thread_id=thread.id,
        root_run_id=run.id,
        run_id=run.id,
    )

    async def generate_explanation(context, session):
        return NodeResult.success({"summary": "讲解已生成"})

    workflow = WorkflowDefinition(
        name="explain",
        version="v1",
        entry_node="generate_explanation",
    )
    workflow.add_node(
        Node(
            name="generate_explanation",
            node_type="action",
            execute=generate_explanation,
        )
    )

    result = await WorkflowEngine(db_session).execute(
        workflow,
        ExecutionContext(run.id, run.user_id, db_session),
        run,
    )
    await db_session.flush()
    run_id = run.id
    user_id = run.user_id
    thread_id = thread.id
    db_session.expire(run)
    persisted_run = await db_session.scalar(
        select(AgentRun).where(AgentRun.id == run_id)
    )
    page = await AgentTimelineService(db_session).get_timeline(
        user_id=user_id,
        thread_id=thread_id,
        before=None,
        limit=20,
    )

    assert result.status.value == "completed"
    assert persisted_run.current_public_step == "generate_explanation"
    assert page.items[0]["workflow"]["current_step"] == "组织讲解"
