"""Plan 审批恢复、拒绝终止与事实投影的 worker 级测试。"""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.models.mysql_models import (
    CanonicalChapter,
    Chapter,
    Document,
    ExamOutline,
    KnowledgePoint,
    Subject,
)
from app.modules.agent.memory_projection import project_completed_run_facts
from app.modules.agent.models import (
    AgentApproval,
    AgentArtifact,
    AgentCheckpoint,
    AgentEvent,
    AgentInput,
    AgentMemoryEvent,
    AgentMemoryItem,
    AgentMemorySnapshot,
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
from app.modules.agent.service import AgentService
from app.modules.agent.worker import AgentWorker


PLAN_TABLES = [
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
    AgentMemorySnapshot.__table__,
    AgentMemoryItem.__table__,
    Subject.__table__,
    Chapter.__table__,
    ExamOutline.__table__,
    CanonicalChapter.__table__,
    Document.__table__,
    KnowledgePoint.__table__,
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
                tables=PLAN_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _create_plan_run(
    db_session,
    *,
    run_id: str,
    seed_learning_goal: bool = True,
) -> AgentRun:
    thread = AgentThread(
        id=f"thread_{run_id}",
        user_id="user_001",
        title="Plan 审批测试",
        status="active",
    )
    run = AgentRun(
        id=run_id,
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="plan",
        workflow_key="plan",
        workflow_version="v1",
        status="queued",
        input_message="帮我制定学习计划",
        presentation="compact",
        public_title="调整学习计划",
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    run.root_run_id = run.id
    if seed_learning_goal:
        db_session.add(
            AgentMemoryItem(
                id=f"memory_{run_id}",
                user_id="user_001",
                scope="user",
                item_type="learning_goal",
                item_key=f"plan_confirmed:seed:{run_id}",
                status="active",
                content_text="二分查找复习目标",
                metadata_json={
                    "period": "7天",
                    "goals": [
                        {
                            "subject": "二分查找",
                            "target": "掌握边界条件",
                            "daily_minutes": 30,
                        }
                    ],
                },
            )
        )
        await db_session.flush()
    return run


@pytest.mark.asyncio
async def test_plan_without_real_memory_fails_before_creating_approval(db_session):
    run = await _create_plan_run(
        db_session,
        run_id="run_plan_without_evidence",
        seed_learning_goal=False,
    )

    assert await AgentWorker().process_run(db_session, run) is True

    assert run.status == "failed"
    assert run.error_message == "缺少学习数据，无法生成计划"
    approval = await db_session.scalar(
        select(AgentApproval).where(AgentApproval.run_id == run.id)
    )
    assert approval is None


@pytest.mark.asyncio
async def test_rejected_plan_stops_without_outbox_or_artifact(db_session):
    run = await _create_plan_run(db_session, run_id="run_plan_rejected_001")

    assert await AgentWorker().process_run(db_session, run) is True
    assert run.status == "waiting_for_approval"
    approval = await db_session.scalar(
        select(AgentApproval).where(AgentApproval.run_id == run.id)
    )
    checkpoint = await db_session.scalar(
        select(AgentCheckpoint).where(AgentCheckpoint.run_id == run.id)
    )
    assert approval is not None
    assert checkpoint is not None

    decided = await AgentService(db_session).decide_approval(
        run.id,
        approval.id,
        "rejected",
        "user_001",
    )

    assert decided is approval
    assert approval.status == "rejected"
    assert run.status == "failed"
    assert run.error_message == "用户拒绝了计划变更"
    checkpoints = list(
        (await db_session.execute(select(AgentCheckpoint))).scalars()
    )
    outboxes = list((await db_session.execute(select(AgentRunOutbox))).scalars())
    artifacts = list((await db_session.execute(select(AgentArtifact))).scalars())
    memory_events = list(
        (await db_session.execute(select(AgentMemoryEvent))).scalars()
    )
    assert checkpoints == []
    assert outboxes == []
    assert artifacts == []
    assert memory_events == []


@pytest.mark.asyncio
async def test_plan_apply_node_rejects_unapproved_checkpoint(db_session):
    """即使外部错误地恢复 Run，应用节点也必须复核真实审批状态。"""
    run = await _create_plan_run(db_session, run_id="run_plan_guard_001")

    assert await AgentWorker().process_run(db_session, run) is True
    assert run.status == "waiting_for_approval"
    run.status = "running"

    assert await AgentWorker().process_run(db_session, run) is True
    assert run.status == "failed"
    artifacts = list((await db_session.execute(select(AgentArtifact))).scalars())
    memory_events = list(
        (await db_session.execute(select(AgentMemoryEvent))).scalars()
    )
    assert artifacts == []
    assert memory_events == []


@pytest.mark.asyncio
async def test_approved_plan_resumes_and_creates_artifact(db_session):
    run = await _create_plan_run(db_session, run_id="run_plan_approved_001")

    assert await AgentWorker().process_run(db_session, run) is True
    approval = await db_session.scalar(
        select(AgentApproval).where(AgentApproval.run_id == run.id)
    )
    assert approval is not None

    decided = await AgentService(db_session).decide_approval(
        run.id,
        approval.id,
        "approved",
        "user_001",
    )

    assert decided is approval
    assert approval.status == "approved"
    assert run.status == "running"
    assert await AgentWorker().process_run(db_session, run) is True
    assert run.status == "completed"
    artifact = await db_session.scalar(
        select(AgentArtifact).where(AgentArtifact.run_id == run.id)
    )
    assert artifact is not None
    assert artifact.artifact_type == "plan"
    assert artifact.content_json["content"]["goals"] == [
        {
            "subject": "二分查找",
            "target": "掌握边界条件",
            "daily_minutes": 30,
            "source": "approved_goal",
            "source_id": f"memory_{run.id}",
        }
    ]
    assert "操作系统" not in str(artifact.content_json)
    assert "计算机网络" not in str(artifact.content_json)
    assert artifact.content_json["approval_id"] == approval.id
    memory_event = await db_session.scalar(
        select(AgentMemoryEvent).where(AgentMemoryEvent.run_id == run.id)
    )
    assert memory_event is not None
    assert memory_event.fact_type == "plan_confirmed"
    assert memory_event.memory_scope == "user"
    assert memory_event.source_kind == "artifact"
    assert memory_event.idempotency_key == f"plan_confirmed:{approval.id}"
    assert memory_event.payload_json == {
        "artifact_id": artifact.id,
        "approval_id": approval.id,
        "memory_snapshot_id": None,
    }
    await project_completed_run_facts(db_session, run, artifact)
    replayed_events = list(
        (
            await db_session.execute(
                select(AgentMemoryEvent).where(AgentMemoryEvent.run_id == run.id)
            )
        ).scalars()
    )
    assert len(replayed_events) == 1
