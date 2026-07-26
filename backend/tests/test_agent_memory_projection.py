"""完成事实投影：评分证据回写掌握度的幂等与跳过语义。"""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.memory_projection import project_completed_run_facts
from app.modules.agent.models import (
    AgentApproval,
    AgentArtifact,
    AgentCheckpoint,
    AgentEvent,
    AgentInput,
    AgentMemoryEvent,
    AgentMessage,
    AgentRun,
    AgentRunOutbox,
    AgentStep,
    AgentThread,
    AgentThreadEvent,
    AgentThreadItem,
    UserLearningMastery,
)
from app.modules.agent.worker import AgentWorker
from app.modules.agent.workflows.contracts import ExecutionContext
from app.modules.agent.workflows.grade import _render_artifact_node

PROJECTION_TABLES = [
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
    UserLearningMastery.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=PROJECTION_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _create_run(
    db_session,
    *,
    run_id: str,
    workflow: str = "grade",
    user_id: str = "user_001",
) -> AgentRun:
    thread = AgentThread(
        id=f"thread_{run_id}",
        user_id=user_id,
        title="评分投影测试",
        status="active",
    )
    run = AgentRun(
        id=run_id,
        thread_id=thread.id,
        user_id=user_id,
        workflow_name=workflow,
        workflow_key=workflow,
        workflow_version="v1",
        status="queued",
        input_message="帮我批改这道题",
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    return run


async def _create_feedback_artifact(
    db_session,
    *,
    run_id: str,
    artifact_id: str,
    grading: dict | None,
) -> AgentArtifact:
    content = {
        "overall": "作答已收到",
        "strengths": [],
        "weaknesses": [],
        "suggestions": [],
    }
    if grading is not None:
        content["grading"] = grading
    artifact = AgentArtifact(
        id=artifact_id,
        run_id=run_id,
        artifact_type="feedback",
        content_json={
            "type": "feedback",
            "title": "批改反馈",
            "content": content,
            "summary": "作答已收到",
        },
    )
    db_session.add(artifact)
    await db_session.flush()
    return artifact


@pytest.mark.asyncio
async def test_grade_projection_updates_mastery_and_replays_idempotently(db_session):
    run_first = await _create_run(db_session, run_id="run_grade_001")
    artifact_first = await _create_feedback_artifact(
        db_session,
        run_id=run_first.id,
        artifact_id="art_grade_001",
        grading={
            "verdict": "correct",
            "question_id": "question_binary_001",
            "knowledge_point_ids": ["kp_binary_search"],
            "subject_id": "subject_ds",
            "evidence_id": "grade_ev_001",
            "score": 1.0,
        },
    )

    await project_completed_run_facts(db_session, run_first, artifact_first)

    mastery = await db_session.scalar(
        select(UserLearningMastery).where(
            UserLearningMastery.user_id == "user_001",
            UserLearningMastery.knowledge_point_id == "kp_binary_search",
        )
    )
    assert mastery is not None
    assert mastery.mastery_score == 1.0
    assert mastery.evidence_count == 1
    assert mastery.correct_count == 1
    assert mastery.incorrect_count == 0
    assert mastery.last_evidence_id == "grade_ev_001"
    assert mastery.subject_id == "subject_ds"

    event = await db_session.scalar(
        select(AgentMemoryEvent).where(AgentMemoryEvent.run_id == run_first.id)
    )
    assert event is not None
    assert event.fact_type == "grade_result_confirmed"
    assert event.idempotency_key == "grade_result_confirmed:user_001:grade_ev_001"
    assert event.payload_json["verdict"] == "correct"
    assert event.payload_json["knowledge_point_ids"] == ["kp_binary_search"]

    # 同一证据重放：事件和掌握度都不重复计数。
    await project_completed_run_facts(db_session, run_first, artifact_first)
    events = list(
        (await db_session.execute(select(AgentMemoryEvent))).scalars()
    )
    assert len(events) == 1
    assert mastery.evidence_count == 1

    # 第二条真实证据（答错）：掌握度按增量公式下降。
    run_second = await _create_run(db_session, run_id="run_grade_002")
    artifact_second = await _create_feedback_artifact(
        db_session,
        run_id=run_second.id,
        artifact_id="art_grade_002",
        grading={
            "verdict": "incorrect",
            "question_id": "question_binary_002",
            "knowledge_point_ids": ["kp_binary_search"],
            "evidence_id": "grade_ev_002",
            "error_types": ["boundary_condition"],
        },
    )
    await project_completed_run_facts(db_session, run_second, artifact_second)

    assert mastery.mastery_score == 0.5
    assert mastery.evidence_count == 2
    assert mastery.correct_count == 1
    assert mastery.incorrect_count == 1
    assert mastery.last_evidence_id == "grade_ev_002"


@pytest.mark.asyncio
async def test_grade_projection_deduplicates_knowledge_points_and_scopes_evidence_by_user(
    db_session,
):
    """重复知识点只计一次；外部证据 ID 相同也不能跨用户互相吞事件。"""
    shared_evidence_id = "external_grade_001"
    first_run = await _create_run(db_session, run_id="run_grade_scope_001")
    first_artifact = await _create_feedback_artifact(
        db_session,
        run_id=first_run.id,
        artifact_id="art_grade_scope_001",
        grading={
            "verdict": "correct",
            "question_id": "question_binary_001",
            "knowledge_point_ids": [
                "kp_binary_search",
                "kp_binary_search",
                " kp_binary_search ",
            ],
            "evidence_id": shared_evidence_id,
        },
    )
    second_run = await _create_run(
        db_session,
        run_id="run_grade_scope_002",
        user_id="user_002",
    )
    second_artifact = await _create_feedback_artifact(
        db_session,
        run_id=second_run.id,
        artifact_id="art_grade_scope_002",
        grading={
            "verdict": "incorrect",
            "question_id": "question_binary_002",
            "knowledge_point_ids": ["kp_binary_search"],
            "evidence_id": shared_evidence_id,
        },
    )

    await project_completed_run_facts(db_session, first_run, first_artifact)
    await project_completed_run_facts(db_session, second_run, second_artifact)

    masteries = list(
        (
            await db_session.execute(
                select(UserLearningMastery).order_by(UserLearningMastery.user_id)
            )
        ).scalars()
    )
    assert [(item.user_id, item.evidence_count, item.mastery_score) for item in masteries] == [
        ("user_001", 1, 1.0),
        ("user_002", 1, 0.0),
    ]
    events = list(
        (
            await db_session.execute(
                select(AgentMemoryEvent).order_by(AgentMemoryEvent.user_id)
            )
        ).scalars()
    )
    assert len(events) == 2
    assert events[0].idempotency_key != events[1].idempotency_key


@pytest.mark.asyncio
async def test_feedback_without_structured_grading_is_ignored(db_session):
    run = await _create_run(db_session, run_id="run_grade_canned")
    artifact = await _create_feedback_artifact(
        db_session,
        run_id=run.id,
        artifact_id="art_grade_canned",
        grading=None,
    )

    await project_completed_run_facts(db_session, run, artifact)

    events = list((await db_session.execute(select(AgentMemoryEvent))).scalars())
    masteries = list((await db_session.execute(select(UserLearningMastery))).scalars())
    assert events == []
    assert masteries == []


@pytest.mark.asyncio
async def test_grade_renderer_carries_explicit_structured_evidence(db_session):
    """未来确定性评分节点写入上下文后，Feedback Artifact 会保留证据契约。"""
    context = ExecutionContext(
        run_id="run_grade_render",
        user_id="user_001",
        db=db_session,
    )
    context.set(
        "feedback",
        {
            "overall": "回答正确",
            "strengths": ["边界处理正确"],
            "weaknesses": [],
            "suggestions": [],
        },
    )
    grading_evidence = {
        "verdict": "correct",
        "question_id": "question_binary_001",
        "knowledge_point_ids": ["kp_binary_search"],
        "evidence_id": "grade_ev_render_001",
    }
    context.set("grading_evidence", grading_evidence)

    result = await _render_artifact_node(context, db_session)

    assert result.artifact is not None
    assert result.artifact["content"]["grading"] == grading_evidence


@pytest.mark.asyncio
async def test_grade_run_with_canned_feedback_does_not_touch_mastery(db_session):
    """当前 P1 grade 工作流没有真实判定，整个 run 完成后不得产生掌握度。"""
    run = await _create_run(db_session, run_id="run_grade_worker")
    run.root_run_id = run.id

    assert await AgentWorker().process_run(db_session, run) is True
    assert run.status == "completed"

    artifact = await db_session.scalar(
        select(AgentArtifact).where(AgentArtifact.run_id == run.id)
    )
    assert artifact is not None
    assert artifact.artifact_type == "feedback"
    assert "grading" not in artifact.content_json["content"]

    events = list((await db_session.execute(select(AgentMemoryEvent))).scalars())
    masteries = list((await db_session.execute(select(UserLearningMastery))).scalars())
    assert events == []
    assert masteries == []
