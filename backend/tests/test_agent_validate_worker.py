"""Validate workflow 在缺少主题时的澄清与恢复测试。"""

from unittest.mock import AsyncMock
from uuid import UUID

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
    AgentMemoryEvent,
    AgentMemoryUpdateOutbox,
    AgentMessage,
    AgentRun,
    AgentRunOutbox,
    AgentStep,
    AgentThread,
    AgentThreadEvent,
    AgentThreadItem,
)
from app.modules.agent.memory_projection import project_completed_run_facts
from app.modules.agent.service import AgentService
from app.modules.agent.timeline import AgentTimelineService
from app.modules.agent.tools import retrieve_knowledge as retrieve_module
from app.modules.agent.worker import AgentWorker
from app.modules.agent.workflows import validate
from app.modules.agent.memory_selector import PracticeBundle, TopicBundle
from app.modules.agent.model_runtime.schema import GeneratedPracticeQuestion
from app.models.mysql_models import Question
from app.modules.practice.models import PracticeSession, PracticeSessionQuestion
from app.modules.practice.models import PracticeAnswer
from app.modules.practice.router import _submit
from app.modules.learning.models import LearningActivityEvent
from app.modules.identity.models import User  # noqa: F401 - register identity FK metadata

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
    Question.__table__,
    PracticeSession.__table__,
    PracticeSessionQuestion.__table__,
    PracticeAnswer.__table__,
    LearningActivityEvent.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        # Validate now crosses the real Agent → Practice persistence boundary;
        # create the complete metadata graph so all ownership/source FKs remain active.
        await connection.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        session.add(
            User(
                id=UUID("01900000-0000-7000-8000-000000000001"),
                email_normalized="validate@example.com",
                email_display="validate@example.com",
                status="active",
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


async def _create_validate_run(db_session, *, run_id: str) -> AgentRun:
    thread = AgentThread(
        id=f"thread_{run_id}",
        user_id="01900000000070008000000000000001",
        title="Validate 澄清测试",
        status="active",
    )
    run = AgentRun(
        id=run_id,
        thread_id=thread.id,
        user_id="01900000000070008000000000000001",
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


async def _create_question(db_session, question_id: str, topic: str) -> None:
    db_session.add(
        Question(
            id=question_id,
            type="choice",
            content=f"{topic}测试题",
            options=[{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
            answer="A",
            explanation=f"{topic}解析",
            difficulty="medium",
            source="测试题库",
            topic_terms=[topic],
            knowledge_point_ids=[],
            answer_source="manual",
            explanation_source="manual",
            review_status="approved",
            status="active",
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_validate_waits_for_topic_clarification_and_resumes_with_answer(
    db_session,
    monkeypatch,
):
    run = await _create_validate_run(db_session, run_id="run_validate_clarify_001")
    await _create_question(db_session, "question_001", "红黑树")
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
        user_id="01900000000070008000000000000001",
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
        "01900000000070008000000000000001",
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


@pytest.mark.asyncio
async def test_validate_completion_writes_practice_fact_event_for_exclusion(
    db_session,
    monkeypatch,
):
    run = await _create_validate_run(db_session, run_id="run_validate_fact_001")
    await _create_question(db_session, "question_binary_001", "二分查找")
    monkeypatch.setattr(
        validate,
        "load_practice_bundle",
        AsyncMock(
            return_value=PracticeBundle(
                topic=TopicBundle(
                    title="二分查找",
                    entity_type="knowledge_point",
                    entity_id="kp_binary_search",
                    aliases=["折半查找"],
                    source="snapshot",
                )
            )
        ),
    )
    retrieve = AsyncMock(
        return_value={
            "status": "success",
            "results": [
                {
                    "entity_id": "question_binary_001",
                    "entity_type": "question",
                    "entity_title": "[1] 二分查找练习",
                    "subject_id": "subject_ds",
                    "question_meta": {
                        "question_type": "analysis",
                        "difficulty": "medium",
                        "source": "真题卷",
                        "paper_name": "查找专项",
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
    assert run.status == "completed"

    artifact = await db_session.scalar(
        select(AgentArtifact).where(AgentArtifact.run_id == run.id)
    )
    assert artifact is not None
    assert artifact.content_json["content"]["question_ids"] == ["question_binary_001"]

    events = list(
        (
            await db_session.execute(
                select(AgentMemoryEvent).where(AgentMemoryEvent.run_id == run.id)
            )
        ).scalars()
    )
    assert len(events) == 1
    event = events[0]
    assert event.fact_type == "practice_artifact_created"
    assert event.memory_scope == "user"
    assert event.source_kind == "artifact"
    assert event.idempotency_key == f"practice_artifact_created:{run.id}"
    assert event.payload_json["artifact_id"] == artifact.id
    assert event.payload_json["question_ids"] == ["question_binary_001"]

    # 重放完成投影不会产生第二条事实事件。
    await project_completed_run_facts(db_session, run, artifact)
    replayed = list(
        (
            await db_session.execute(
                select(AgentMemoryEvent).where(AgentMemoryEvent.run_id == run.id)
            )
        ).scalars()
    )
    assert len(replayed) == 1


@pytest.mark.asyncio
async def test_validate_worker_keeps_generated_answer_out_of_public_artifact(
    db_session,
    monkeypatch,
):
    run = await _create_validate_run(db_session, run_id="run_validate_generated_001")
    monkeypatch.setattr(
        validate,
        "load_practice_bundle",
        AsyncMock(
            return_value=PracticeBundle(
                topic=TopicBundle(
                    title="UDP",
                    entity_type="topic",
                    source="current_turn",
                )
            )
        ),
    )
    monkeypatch.setattr(
        retrieve_module,
        "retrieve_knowledge",
        AsyncMock(return_value={"status": "success", "results": [], "total": 0}),
    )
    monkeypatch.setattr(
        validate.practice_generation_runtime,
        "generate",
        AsyncMock(
            return_value=GeneratedPracticeQuestion(
                content="UDP 是否保证可靠交付？",
                options=[
                    {"key": "A", "text": "不保证"},
                    {"key": "B", "text": "保证"},
                ],
                answer="A",
                explanation="UDP 不提供可靠交付保证。",
            )
        ),
    )

    assert await AgentWorker().process_run(db_session, run) is True

    artifact = await db_session.scalar(
        select(AgentArtifact).where(AgentArtifact.run_id == run.id)
    )
    practice = await db_session.scalar(
        select(PracticeSession).where(PracticeSession.agent_run_id == run.id)
    )
    assert artifact is not None
    assert practice is not None
    assert practice.status == "draft"
    assert practice.started_at is None
    assert practice.agent_thread_id == run.thread_id
    assert artifact.content_json["content"]["practice_session_id"] == practice.id
    assert artifact.content_json["content"]["actions"] == [
        {"type": "open_practice", "target_id": practice.id, "label": "开始练习"}
    ]
    assert "generated_questions" not in artifact.content_json["content"]
    assert "standard_answer" not in str(artifact.content_json)
    assert artifact.metadata_json["generated_questions"][0]["standard_answer"] == "A"

    item = await db_session.scalar(
        select(PracticeSessionQuestion).where(
            PracticeSessionQuestion.session_id == practice.id
        )
    )
    assert item is not None
    practice.status = "active"
    practice.started_at = artifact.created_at
    db_session.add(
        PracticeAnswer(
            session_id=practice.id,
            session_question_id=item.id,
            question_id=None,
            user_answer="A",
            version=1,
        )
    )
    await db_session.flush()
    await _submit(db_session, practice)
    learning_event = await db_session.scalar(
        select(LearningActivityEvent).where(
            LearningActivityEvent.source_id == f"{practice.id}:{item.item_id}"
        )
    )
    assert learning_event is not None
    assert learning_event.source_type == "agent_practice"
    assert learning_event.topic_keywords_json == ["udp"]
    assert learning_event.is_correct is True
