"""Grade workflow 的 EvaluationBundle 与真实客观题证据闭环。"""

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
    Question,
    QuestionKnowledgeLink,
    Subject,
)
from app.modules.agent.models import (
    AgentApproval,
    AgentArtifact,
    AgentCheckpoint,
    AgentEvent,
    AgentInput,
    AgentMemoryEvent,
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
from app.modules.agent.worker import AgentWorker
from app.modules.agent.workflows.grade import _normalize_answer


GRADE_TABLES = [
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
    UserLearningMastery.__table__,
    Subject.__table__,
    Chapter.__table__,
    ExamOutline.__table__,
    CanonicalChapter.__table__,
    Document.__table__,
    Question.__table__,
    QuestionKnowledgeLink.__table__,
]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=GRADE_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _create_grade_run(
    db_session,
    *,
    run_id: str,
    question_type: str = "choice",
    standard_answer: str = "B",
    raw_input: str = "我的答案是 B，请帮我批改",
) -> AgentRun:
    thread = AgentThread(
        id=f"thread_{run_id}",
        user_id="user_001",
        title="Grade 测试",
        status="active",
    )
    run = AgentRun(
        id=run_id,
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="grade",
        workflow_key="grade",
        workflow_version="v1",
        status="queued",
        input_message=raw_input,
        metadata_json={"memory_snapshot_id": f"snapshot_{run_id}"},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    run.root_run_id = run.id
    question = Question(
        id=f"question_{run_id}",
        type=question_type,
        content="二分查找每轮将搜索区间缩小到多少？",
        options=[
            {"key": "A", "text": "四分之一"},
            {"key": "B", "text": "约一半"},
        ],
        answer=standard_answer,
        answer_source="manual",
        explanation="每轮排除约一半区间。",
        knowledge_point_ids=["kp_binary_search"],
        review_status="approved",
        status="active",
    )
    db_session.add(question)
    await db_session.flush()
    db_session.add(
        AgentMemorySnapshot(
            id=f"snapshot_{run_id}",
            run_id=run.id,
            thread_id=thread.id,
            user_id="user_001",
            state_version=1,
            standalone_request=raw_input,
            understanding_json={
                "raw_input": raw_input,
                "reference_sources": [
                    {"type": "question", "id": question.id}
                ],
            },
        )
    )
    await db_session.flush()
    return run


@pytest.mark.asyncio
async def test_grade_worker_projects_real_objective_verdict_to_mastery(db_session):
    run = await _create_grade_run(db_session, run_id="grade_objective_001")

    assert await AgentWorker().process_run(db_session, run) is True
    assert run.status == "completed"

    artifact = await db_session.scalar(
        select(AgentArtifact).where(AgentArtifact.run_id == run.id)
    )
    assert artifact is not None
    assert artifact.artifact_type == "feedback"
    assert artifact.content_json["content"]["overall"] == "回答正确"
    grading = artifact.content_json["content"]["grading"]
    assert grading == {
        "verdict": "correct",
        "question_id": "question_grade_objective_001",
        "knowledge_point_ids": ["kp_binary_search"],
        "subject_id": None,
        "evidence_id": run.id,
        "score": 1.0,
        "error_types": [],
        "answer_source": "manual",
    }

    mastery = await db_session.scalar(select(UserLearningMastery))
    assert mastery is not None
    assert mastery.user_id == "user_001"
    assert mastery.knowledge_point_id == "kp_binary_search"
    assert mastery.mastery_score == 1.0
    assert mastery.evidence_count == 1
    assert mastery.correct_count == 1
    assert mastery.last_evidence_id == run.id

    event = await db_session.scalar(select(AgentMemoryEvent))
    assert event is not None
    assert event.fact_type == "grade_result_confirmed"
    assert event.payload_json["question_id"] == "question_grade_objective_001"
    assert event.payload_json["verdict"] == "correct"


@pytest.mark.asyncio
async def test_grade_worker_records_incorrect_objective_verdict(db_session):
    run = await _create_grade_run(
        db_session,
        run_id="grade_incorrect_001",
        raw_input="我的答案是 A，请帮我批改",
    )

    assert await AgentWorker().process_run(db_session, run) is True
    assert run.status == "completed"

    artifact = await db_session.scalar(
        select(AgentArtifact).where(AgentArtifact.run_id == run.id)
    )
    grading = artifact.content_json["content"]["grading"]
    assert artifact.content_json["content"]["overall"] == "回答错误"
    assert grading["verdict"] == "incorrect"
    assert grading["score"] == 0.0
    assert grading["error_types"] == ["answer_mismatch"]

    mastery = await db_session.scalar(select(UserLearningMastery))
    assert mastery.mastery_score == 0.0
    assert mastery.evidence_count == 1
    assert mastery.incorrect_count == 1


@pytest.mark.asyncio
async def test_grade_worker_rejects_subjective_question_before_artifact(db_session):
    run = await _create_grade_run(
        db_session,
        run_id="grade_subjective_001",
        question_type="short_answer",
        standard_answer="目标始终位于当前搜索区间内",
        raw_input="我的答案是 保持左右边界，请帮我批改",
    )

    assert await AgentWorker().process_run(db_session, run) is True
    assert run.status == "failed"
    assert "当前仅支持选择题、填空题和判断题" in run.error_message
    assert await db_session.scalar(
        select(AgentArtifact).where(AgentArtifact.run_id == run.id)
    ) is None
    assert await db_session.scalar(select(AgentMemoryEvent)) is None
    assert await db_session.scalar(select(UserLearningMastery)) is None


def test_grade_normalizes_fill_and_negative_judge_answers():
    assert _normalize_answer(" 42 ", "fill") == "42"
    assert _normalize_answer("不对", "judge") == "false"
    assert _normalize_answer("错误", "judge") == "false"
    assert _normalize_answer("正确", "judge") == "true"
