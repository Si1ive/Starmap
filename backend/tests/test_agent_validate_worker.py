"""Validate workflow 在缺少主题时的澄清与恢复测试。"""

from unittest.mock import AsyncMock

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
from app.modules.agent.service import AgentService
from app.modules.agent.timeline import AgentTimelineService
from app.modules.agent.tools import retrieve_knowledge as retrieve_module
from app.modules.agent.worker import AgentWorker
from app.modules.agent.workflows import validate
from app.modules.agent.memory_selector import PracticeBundle

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


async def _create_validate_run(db_session, *, run_id: str) -> AgentRun:
    thread = AgentThread(
        id=f"thread_{run_id}",
        user_id="user_001",
        title="Validate 澄清测试",
        status="active",
    )
    run = AgentRun(
        id=run_id,
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        workflow_key="validate",
        workflow_version="v1",
        status="queued",
        input_message="给我出一道题",
        presentation="compact",
        public_title="生成专项练习",
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
    return run


@pytest.mark.asyncio
async def test_validate_waits_for_topic_clarification_and_resumes_with_answer(
    db_session,
    monkeypatch,
):
    run = await _create_validate_run(db_session, run_id="run_validate_clarify_001")
    monkeypatch.setattr(
        validate,
        "load_practice_bundle",
        AsyncMock(return_value=PracticeBundle()),
    )
    retrieve = AsyncMock(
        return_value={
            "status": "success",
            "results": [
                {
                    "entity_id": "question_001",
                    "entity_type": "question",
                    "entity_title": "[1] 红黑树练习",
                    "subject_id": "subject_ds",
                    "question_meta": {
                        "question_type": "analysis",
                        "difficulty": "medium",
                        "source": "练习册",
                        "paper_name": "平衡树专项",
                        "answer_source": "manual",
                        "review_status": "approved",
                        "status": "active",
                    },
                }
            ],
            "total": 1,
        }
    )
    monkeypatch.setattr(retrieve_module, "retrieve_knowledge", retrieve)

    assert await AgentWorker().process_run(db_session, run) is True

    waiting_input = await db_session.scalar(
        select(AgentInput).where(AgentInput.run_id == run.id)
    )
    assert run.status == "waiting_for_user"
    assert waiting_input is not None
    assert waiting_input.input_key == "practice_topic"
    assert waiting_input.prompt_ref == "请补充想练习的知识点或题目范围"
    retrieve.assert_not_awaited()

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id=run.thread_id,
        before=None,
        limit=20,
    )
    assert page.items[0]["workflow"]["status"] == "waiting_for_user"
    assert page.items[0]["workflow"]["pending_input"]["question"] == "请补充想练习的知识点或题目范围"

    answered = await AgentService(db_session).submit_input_answer(
        run.id,
        "practice_topic",
        "红黑树",
        "user_001",
    )
    assert answered is not None
    assert answered.status == "answered"
    assert run.status == "running"

    assert await AgentWorker().process_run(db_session, run) is True

    artifact = await db_session.scalar(
        select(AgentArtifact).where(AgentArtifact.run_id == run.id)
    )
    assert run.status == "completed"
    assert artifact is not None
    assert artifact.content_json["content"]["question_count"] == 1
    assert retrieve.await_args.kwargs["query"] == "红黑树"
