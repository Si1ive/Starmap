"""Explain workflow worker 级无资料回退测试。"""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.model_runtime.schema import (
    ActionType,
    ExplanationOutput,
    LoopDecision,
)
from app.modules.agent.memory_projection import project_completed_run_facts
from app.modules.agent.models import (
    AgentApproval,
    AgentArtifact,
    AgentCheckpoint,
    AgentEvent,
    AgentInput,
    AgentMemoryEvent,
    AgentMemoryUpdateOutbox,
    AgentMessage,
    AgentRun,
    AgentRunOutbox,
    AgentStep,
    AgentThread,
    AgentThreadEvent,
    AgentThreadItem,
    UserLearningMastery,
)
from app.modules.agent.thread_events import thread_event_store
from app.modules.agent.timeline import AgentTimelineService
from app.modules.agent.tools import retrieve_knowledge as retrieve_module
from app.modules.agent.worker import AgentWorker
from app.modules.agent.workflows import explain

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
    AgentMemoryEvent.__table__,
    AgentMemoryUpdateOutbox.__table__,
    UserLearningMastery.__table__,
]


class ExplanationRuntimeStub:
    def __init__(self, *, decisions, output):
        self.decisions = list(decisions)
        self.output = output

    async def decide(self, current_input, *, evidence_count, deps, db=None):
        return self.decisions.pop(0)

    async def generate(self, current_input, *, evidence_text, deps, db=None):
        return self.output


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


async def _create_explain_run(db_session, *, run_id: str) -> AgentRun:
    thread = AgentThread(
        id=f"thread_{run_id}",
        user_id="user_001",
        title="Explain 回退测试",
        status="active",
    )
    run = AgentRun(
        id=run_id,
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="explain",
        workflow_key="explain",
        workflow_version="v1",
        status="queued",
        input_message="给我讲解一下红黑树",
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
    return run


def _runtime_output() -> ExplanationOutput:
    return ExplanationOutput(
        outline=["定义", "性质"],
        body="红黑树是一种自平衡二叉搜索树。",
        citations=["不应保留的引用"],
        summary="给出概念性说明。",
    )


@pytest.mark.asyncio
async def test_worker_persists_zero_hit_fallback_answer_without_citations(
    db_session,
    monkeypatch,
):
    run = await _create_explain_run(db_session, run_id="run_explain_empty_001")
    monkeypatch.setattr(
        explain,
        "explanation_runtime",
        ExplanationRuntimeStub(
            decisions=[
                LoopDecision(
                    action=ActionType.RETRIEVE_KNOWLEDGE,
                    parameters={"query": "红黑树", "limit": 5},
                    reasoning="先查询资料",
                    confidence=0.95,
                ),
                LoopDecision(
                    action=ActionType.FINISH,
                    parameters={},
                    reasoning="未命中资料，直接回答",
                    confidence=0.9,
                ),
            ],
            output=_runtime_output(),
        ),
    )
    monkeypatch.setattr(explain.loop_turn_store, "record", AsyncMock())
    monkeypatch.setattr(
        retrieve_module.RetrievalService,
        "search_with_outline_expansion",
        AsyncMock(
            return_value={
                "mode": "hybrid",
                "outline_expansion": {"matched_chapters": []},
                "results": [],
            }
        ),
    )

    assert await AgentWorker().process_run(db_session, run) is True

    artifact = await db_session.scalar(
        select(AgentArtifact).where(AgentArtifact.run_id == run.id)
    )
    memory_event = await db_session.scalar(
        select(AgentMemoryEvent).where(AgentMemoryEvent.run_id == run.id)
    )
    message = await db_session.scalar(
        select(AgentMessage).where(AgentMessage.run_id == run.id)
    )
    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id=run.thread_id,
        before=None,
        limit=20,
    )

    assert run.status == "completed"
    assert artifact is not None
    assert artifact.content_json["citations"] == []
    assert memory_event is not None
    assert memory_event.fact_type == "explanation_artifact_created"
    assert memory_event.memory_scope == "thread"
    assert memory_event.source_kind == "artifact"
    assert memory_event.idempotency_key == f"explanation_artifact_created:{run.id}"
    assert memory_event.payload_json == {
        "artifact_id": artifact.id,
        "memory_snapshot_id": None,
    }
    await project_completed_run_facts(db_session, run, artifact)
    explanation_events = list(
        (
            await db_session.execute(
                select(AgentMemoryEvent).where(AgentMemoryEvent.run_id == run.id)
            )
        ).scalars()
    )
    assert len(explanation_events) == 1
    masteries = list(
        (await db_session.execute(select(UserLearningMastery))).scalars()
    )
    assert masteries == []
    assert message is not None
    assert message.status == "completed"
    assert message.content_text == "红黑树是一种自平衡二叉搜索树。"
    assert [item["type"] for item in page.items] == ["workflow", "message"]
    workflow = page.items[0]["workflow"]
    assert workflow["status"] == "completed"
    assert workflow["activities"][0]["detail"] == "没有检索到相关文档"
    assert workflow["artifacts"][0]["content"]["citations"] == []
    assert page.items[1]["message"]["content"] == "红黑树是一种自平衡二叉搜索树。"

    thread_events = await thread_event_store.get_events(
        db_session,
        run.thread_id,
        after_sequence=0,
        limit=50,
    )
    assert "message.completed" in [event.event_type for event in thread_events]


@pytest.mark.asyncio
async def test_worker_persists_retrieval_error_fallback_answer_without_citations(
    db_session,
    monkeypatch,
):
    run = await _create_explain_run(db_session, run_id="run_explain_error_001")
    monkeypatch.setattr(
        explain,
        "explanation_runtime",
        ExplanationRuntimeStub(
            decisions=[
                LoopDecision(
                    action=ActionType.RETRIEVE_KNOWLEDGE,
                    parameters={"query": "红黑树", "limit": 5},
                    reasoning="先查询资料",
                    confidence=0.95,
                ),
                LoopDecision(
                    action=ActionType.FINISH,
                    parameters={},
                    reasoning="检索失败，改为通用回答",
                    confidence=0.9,
                ),
            ],
            output=_runtime_output(),
        ),
    )
    monkeypatch.setattr(explain.loop_turn_store, "record", AsyncMock())
    monkeypatch.setattr(
        retrieve_module.RetrievalService,
        "search_with_outline_expansion",
        AsyncMock(side_effect=RuntimeError("qdrant unavailable")),
    )

    assert await AgentWorker().process_run(db_session, run) is True

    artifact = await db_session.scalar(
        select(AgentArtifact).where(AgentArtifact.run_id == run.id)
    )
    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id=run.thread_id,
        before=None,
        limit=20,
    )

    assert run.status == "completed"
    assert artifact is not None
    assert artifact.content_json["citations"] == []
    workflow = page.items[0]["workflow"]
    assert workflow["activities"][0]["status"] == "failed"
    assert workflow["activities"][0]["detail"] == "暂时无法检索相关文档"
    assert workflow["artifacts"][0]["content"]["citations"] == []
    assert page.items[1]["message"]["status"] == "completed"
    assert page.items[1]["message"]["content"] == "红黑树是一种自平衡二叉搜索树。"

    thread_events = await thread_event_store.get_events(
        db_session,
        run.thread_id,
        after_sequence=0,
        limit=50,
    )
    assert "workflow.artifact.created" in [
        event.event_type for event in thread_events
    ]
