"""Agent 对话 turn 与 thread 时间线服务测试。"""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.models import (
    AgentApproval,
    AgentArtifact,
    AgentEvent,
    AgentInput,
    AgentMessage,
    AgentModelConfigRecord,
    AgentRun,
    AgentRunOutbox,
    AgentStep,
    AgentThread,
    AgentThreadEvent,
    AgentThreadItem,
)
from app.modules.agent.service import AgentService
from app.modules.agent.events import event_store
from app.modules.agent.thread_events import thread_event_store
from app.modules.agent.timeline import AgentTimelineService, TurnConflictError

TIMELINE_SERVICE_TABLES = [
    AgentModelConfigRecord.__table__,
    AgentThread.__table__,
    AgentRun.__table__,
    AgentMessage.__table__,
    AgentThreadItem.__table__,
    AgentThreadEvent.__table__,
    AgentStep.__table__,
    AgentEvent.__table__,
    AgentRunOutbox.__table__,
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
                tables=TIMELINE_SERVICE_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _create_thread(db_session, thread_id: str = "thread_001") -> AgentThread:
    thread = AgentThread(
        id=thread_id,
        user_id="user_001",
        title="新会话",
        status="active",
    )
    db_session.add(thread)
    await db_session.flush()
    return thread


async def _create_turn(
    db_session,
    *,
    content: str = "解释循环队列",
    client_message_id: str = "client_001",
    model_config_id: str | None = None,
):
    return await AgentTimelineService(db_session).create_turn(
        user_id="user_001",
        thread_id="thread_001",
        content=content,
        client_message_id=client_message_id,
        attachments=[],
        context_refs=[],
        model_config_id=model_config_id,
    )


@pytest.mark.asyncio
async def test_create_turn_writes_message_run_timeline_event_and_outbox(db_session):
    thread = await _create_thread(db_session)

    creation = await _create_turn(db_session)

    assert creation.timeline_cursor == 1
    assert creation.message.status == "completed"
    assert creation.message.run_id == creation.run.id
    assert creation.run.root_run_id == creation.run.id
    assert creation.run.workflow_key == "conversation"
    assert thread.last_item_sequence == 1
    assert thread.title == "解释循环队列"

    items = list(
        (
            await db_session.execute(
                select(AgentThreadItem).order_by(AgentThreadItem.sequence)
            )
        ).scalars()
    )
    assert [(item.sequence, item.item_type) for item in items] == [(1, "message")]
    assert creation.run.presentation == "silent"
    assert await db_session.scalar(select(func.count(AgentEvent.id))) == 1
    assert await db_session.scalar(select(func.count(AgentRunOutbox.id))) == 1


@pytest.mark.asyncio
async def test_create_turn_persists_selected_model_config(db_session):
    await _create_thread(db_session)
    db_session.add(
        AgentModelConfigRecord(
            id="model_001",
            display_name="推理模型",
            model_name="reasoning-model",
            api_key="test-key",
            online=True,
            selectable=True,
            is_default=True,
            default_slot=1,
        )
    )
    await db_session.flush()

    creation = await _create_turn(db_session, model_config_id="model_001")

    assert creation.run.metadata_json["model_config_id"] == "model_001"


@pytest.mark.asyncio
async def test_create_turn_is_idempotent_by_client_message_id(db_session):
    await _create_thread(db_session)

    first = await _create_turn(db_session)
    second = await _create_turn(db_session)

    assert second.message.id == first.message.id
    assert second.run.id == first.run.id
    assert second.timeline_cursor == 1
    assert await db_session.scalar(select(func.count(AgentMessage.id))) == 1
    assert await db_session.scalar(select(func.count(AgentRun.id))) == 1
    assert await db_session.scalar(select(func.count(AgentThreadItem.id))) == 1
    assert await db_session.scalar(select(func.count(AgentRunOutbox.id))) == 1


@pytest.mark.asyncio
async def test_turn_idempotency_rejects_changed_model_selection(db_session):
    await _create_thread(db_session)
    for model_id, display_name in (
        ("model_001", "模型 A"),
        ("model_002", "模型 B"),
    ):
        db_session.add(
            AgentModelConfigRecord(
                id=model_id,
                display_name=display_name,
                model_name=model_id,
                api_key="test-key",
                online=True,
                selectable=True,
            )
        )
    await db_session.flush()
    await _create_turn(db_session, model_config_id="model_001")

    with pytest.raises(TurnConflictError):
        await _create_turn(db_session, model_config_id="model_002")


@pytest.mark.asyncio
async def test_create_turn_rejects_reused_id_with_different_content(db_session):
    await _create_thread(db_session)
    await _create_turn(db_session)

    with pytest.raises(TurnConflictError):
        await _create_turn(db_session, content="换一个问题")


@pytest.mark.asyncio
async def test_timeline_aggregates_child_workflow_into_root_item(db_session):
    await _create_thread(db_session)
    creation = await _create_turn(db_session)
    creation.run.status = "completed"

    child = await AgentService(db_session).create_run(
        user_id="user_001",
        thread_id="thread_001",
        workflow_name="explain",
        input_message="解释循环队列",
        workflow_key="explain",
        workflow_version="v1",
        trigger_message_id=creation.message.id,
        parent_run_id=creation.run.id,
        root_run_id=creation.run.id,
        presentation="compact",
        public_title="整理讲解",
    )
    child.status = "waiting_for_user"
    child.public_summary = "需要确认讲解范围"
    child.current_public_step = "generate_explanation"
    now = datetime.utcnow()
    thread = await db_session.get(AgentThread, "thread_001")
    thread.last_item_sequence += 1
    db_session.add_all(
        [
            AgentThreadItem(
                id="item_workflow_001",
                thread_id="thread_001",
                sequence=thread.last_item_sequence,
                item_type="workflow",
                ref_id=creation.run.id,
                run_id=creation.run.id,
            ),
            AgentStep(
                id="step_001",
                run_id=child.id,
                node_name="generate_explanation",
                node_type="action",
                status="running",
                started_at=now,
            ),
            AgentInput(
                id="input_001",
                run_id=child.id,
                input_key="scope",
                input_schema_version="v1",
                prompt_ref="你希望讲解到什么深度？",
                status="pending",
            ),
            AgentApproval(
                id="approval_001",
                run_id=child.id,
                action_key="apply_learning_plan",
                diff_ref='{"summary": "把循环队列加入本周复习计划"}',
                status="pending",
            ),
            AgentArtifact(
                id="artifact_001",
                run_id=child.id,
                artifact_type="message",
                content_json={"title": "已有结果", "content": "可继续编辑"},
            ),
        ]
    )
    await db_session.flush()
    await event_store.append(
        db_session,
        child.id,
        "tool.called",
        {
            "activity_id": "activity_001",
            "activity_type": "retrieval",
            "title": "检索 408 知识库",
            "detail": "正在查询循环队列",
            "public_metadata": {
                "backend": "Qdrant 混合检索 + MySQL 内容索引",
                "query": "循环队列",
            },
        },
    )
    await event_store.append(
        db_session,
        child.id,
        "tool.result",
        {
            "activity_id": "activity_001",
            "activity_type": "retrieval",
            "title": "检索 408 知识库",
            "detail": "命中 1 份资料",
            "status": "completed",
            "public_metadata": {
                "backend": "Qdrant 混合检索 + MySQL 内容索引",
                "query": "循环队列",
                "total": 1,
                "documents": [{"id": "kp_001", "title": "循环队列"}],
            },
        },
    )

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=50,
    )

    assert [item["type"] for item in page.items] == ["message", "workflow"]
    workflow = page.items[1]["workflow"]
    assert workflow["root_run_id"] == creation.run.id
    assert workflow["status"] == "waiting_for_user"
    assert workflow["title"] == "整理讲解"
    assert workflow["current_step"] == "组织讲解"
    assert workflow["steps"][0]["label"] == "组织讲解"
    assert workflow["activities"] == [
        {
            "id": "activity_001",
            "activity_type": "retrieval",
            "title": "检索 408 知识库",
            "detail": "命中 1 份资料",
            "status": "completed",
            "metadata": {
                "backend": "Qdrant 混合检索 + MySQL 内容索引",
                "query": "循环队列",
                "total": 1,
                "documents": [{"id": "kp_001", "title": "循环队列"}],
            },
            "started_at": workflow["activities"][0]["started_at"],
            "completed_at": workflow["activities"][0]["completed_at"],
        }
    ]
    assert workflow["pending_input"]["input_key"] == "scope"
    assert workflow["pending_input"]["run_id"] == child.id
    assert workflow["pending_approval"]["id"] == "approval_001"
    assert workflow["pending_approval"]["run_id"] == child.id
    assert workflow["artifacts"][0]["type"] == "message"

    activity_events = await thread_event_store.get_events(
        db_session,
        "thread_001",
        after_sequence=creation.timeline_cursor,
        limit=50,
    )
    projected_activities = [
        event for event in activity_events
        if event.event_type == "workflow.activity.updated"
    ]
    assert [event.payload["activity"]["status"] for event in projected_activities] == [
        "running",
        "completed",
    ]


@pytest.mark.asyncio
async def test_timeline_merges_retry_attempts_into_single_public_activity(db_session):
    await _create_thread(db_session)
    creation = await _create_turn(db_session)
    creation.run.status = "completed"

    child = await AgentService(db_session).create_run(
        user_id="user_001",
        thread_id="thread_001",
        workflow_name="explain",
        input_message="解释红黑树",
        workflow_key="explain",
        workflow_version="v1",
        trigger_message_id=creation.message.id,
        parent_run_id=creation.run.id,
        root_run_id=creation.run.id,
        presentation="compact",
        public_title="整理讲解",
    )
    child.status = "running"
    child.current_public_step = "evidence_loop"
    await AgentTimelineService(db_session).ensure_workflow_item(
        thread_id="thread_001",
        root_run_id=creation.run.id,
        run_id=child.id,
    )

    await event_store.append(
        db_session,
        child.id,
        "tool.called",
        {
            "activity_id": "activity_retry_001",
            "logical_activity_id": "activity_retry_001",
            "attempt_id": "attempt_001",
            "attempt_no": 1,
            "activity_type": "retrieval",
            "title": "检索 408 知识库",
            "detail": "正在使用混合检索查询“红黑树”",
            "public_metadata": {
                "query": "红黑树",
                "attempt_no": 1,
            },
        },
    )
    await event_store.append(
        db_session,
        child.id,
        "tool.result",
        {
            "activity_id": "activity_retry_001",
            "logical_activity_id": "activity_retry_001",
            "attempt_id": "attempt_001",
            "attempt_no": 1,
            "activity_type": "retrieval",
            "title": "检索 408 知识库",
            "detail": "暂时无法检索相关文档",
            "status": "failed",
            "public_metadata": {
                "query": "红黑树",
                "attempt_no": 1,
            },
        },
    )
    await event_store.append(
        db_session,
        child.id,
        "tool.called",
        {
            "activity_id": "activity_retry_001",
            "logical_activity_id": "activity_retry_001",
            "attempt_id": "attempt_002",
            "attempt_no": 2,
            "activity_type": "retrieval",
            "title": "检索 408 知识库",
            "detail": "正在第 2 次尝试检索“红黑树”",
            "public_metadata": {
                "query": "红黑树",
                "attempt_no": 2,
            },
        },
    )
    await event_store.append(
        db_session,
        child.id,
        "tool.result",
        {
            "activity_id": "activity_retry_001",
            "logical_activity_id": "activity_retry_001",
            "attempt_id": "attempt_002",
            "attempt_no": 2,
            "activity_type": "retrieval",
            "title": "检索 408 知识库",
            "detail": "混合检索完成，命中 1 份资料",
            "status": "completed",
            "public_metadata": {
                "query": "红黑树",
                "attempt_no": 2,
                "total": 1,
                "documents": [{"id": "kp_rb_tree", "title": "红黑树"}],
            },
        },
    )

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=50,
    )

    workflow = page.items[1]["workflow"]
    assert workflow["activities"] == [
        {
            "id": "activity_retry_001",
            "activity_type": "retrieval",
            "title": "检索 408 知识库",
            "detail": "混合检索完成，命中 1 份资料",
            "status": "completed",
            "metadata": {
                "query": "红黑树",
                "attempt_no": 2,
                "total": 1,
                "documents": [{"id": "kp_rb_tree", "title": "红黑树"}],
            },
            "started_at": workflow["activities"][0]["started_at"],
            "completed_at": workflow["activities"][0]["completed_at"],
        }
    ]

    projected_activities = [
        event for event in (
            await thread_event_store.get_events(
                db_session,
                "thread_001",
                after_sequence=creation.timeline_cursor,
                limit=50,
            )
        )
        if event.event_type == "workflow.activity.updated"
    ]
    assert len(projected_activities) == 4
    assert [
        event.payload["activity"]["metadata"]["attempt_no"]
        for event in projected_activities
    ] == [1, 1, 2, 2]


@pytest.mark.asyncio
async def test_workflow_interactions_emit_thread_events(db_session):
    await _create_thread(db_session)
    creation = await _create_turn(db_session)
    child = await AgentService(db_session).create_run(
        user_id="user_001",
        thread_id="thread_001",
        workflow_name="plan",
        input_message="调整计划",
        workflow_key="plan",
        workflow_version="v1",
        trigger_message_id=creation.message.id,
        parent_run_id=creation.run.id,
        root_run_id=creation.run.id,
        presentation="compact",
        public_title="调整学习计划",
    )
    await AgentTimelineService(db_session).ensure_workflow_item(
        thread_id="thread_001",
        root_run_id=creation.run.id,
        run_id=child.id,
    )
    service = AgentService(db_session)

    agent_input = await service.create_input(
        child.id,
        "scope",
        "请补充需要调整的范围",
    )
    approval = await service.create_approval(
        child.id,
        "apply_learning_plan",
        '{"summary":"应用学习计划调整"}',
    )

    events = await thread_event_store.get_events(
        db_session,
        "thread_001",
        after_sequence=creation.timeline_cursor,
        limit=20,
    )
    interaction_events = [
        event
        for event in events
        if event.event_type in {"workflow.input.required", "workflow.approval.required"}
    ]

    assert [event.event_type for event in interaction_events] == [
        "workflow.input.required",
        "workflow.approval.required",
    ]
    assert interaction_events[0].payload == {
        "sequence": interaction_events[0].sequence,
        "root_run_id": creation.run.id,
        "run_id": child.id,
        "status": "waiting_for_user",
        "input_id": agent_input.id,
        "input_key": "scope",
    }
    assert interaction_events[1].payload == {
        "sequence": interaction_events[1].sequence,
        "root_run_id": creation.run.id,
        "run_id": child.id,
        "status": "waiting_for_approval",
        "approval_id": approval.id,
        "action_key": "apply_learning_plan",
    }


@pytest.mark.asyncio
async def test_input_answer_emits_running_status_to_thread(db_session):
    await _create_thread(db_session)
    creation = await _create_turn(db_session)
    child = await AgentService(db_session).create_run(
        user_id="user_001",
        thread_id="thread_001",
        workflow_name="explain",
        input_message="整理讲解",
        workflow_key="explain",
        workflow_version="v1",
        trigger_message_id=creation.message.id,
        parent_run_id=creation.run.id,
        root_run_id=creation.run.id,
        presentation="compact",
        public_title="整理讲解",
    )
    child.status = "waiting_for_user"
    await AgentTimelineService(db_session).ensure_workflow_item(
        thread_id="thread_001",
        root_run_id=creation.run.id,
        run_id=child.id,
    )
    service = AgentService(db_session)
    agent_input = await service.create_input(
        child.id,
        "scope",
        "请补充需要讲解的范围",
    )
    input_events = await thread_event_store.get_events(
        db_session,
        "thread_001",
        after_sequence=creation.timeline_cursor,
        limit=20,
    )
    cursor_before_answer = input_events[-1].sequence

    answered = await service.submit_input_answer(
        child.id,
        "scope",
        "第二章",
        "user_001",
    )

    assert answered is agent_input
    assert answered.status == "answered"
    assert child.status == "running"
    run_events = list(
        (
            await db_session.execute(
                select(AgentEvent)
                .where(AgentEvent.run_id == child.id)
                .order_by(AgentEvent.sequence)
            )
        )
        .scalars()
        .all()
    )
    assert run_events[-1].event_type == "run.status_changed"
    assert run_events[-1].payload == {
        "from": "waiting_for_user",
        "to": "running",
        "reason": "用户输入已提交",
    }

    thread_events = await thread_event_store.get_events(
        db_session,
        "thread_001",
        after_sequence=cursor_before_answer,
        limit=20,
    )
    assert [event.event_type for event in thread_events] == ["workflow.updated"]
    assert thread_events[0].payload["root_run_id"] == creation.run.id
    assert thread_events[0].payload["run_id"] == child.id
    assert thread_events[0].payload["status"] == "running"
    assert thread_events[0].payload["reason"] == "用户输入已提交"


@pytest.mark.asyncio
async def test_workflow_interactions_require_owned_run_in_matching_wait_state(
    db_session,
):
    await _create_thread(db_session)
    creation = await _create_turn(db_session)
    service = AgentService(db_session)

    input_run = await service.create_run(
        user_id="user_001",
        thread_id="thread_001",
        workflow_name="explain",
        input_message="整理讲解",
        parent_run_id=creation.run.id,
        root_run_id=creation.run.id,
        presentation="compact",
    )
    input_run.status = "waiting_for_user"
    agent_input = await service.create_input(
        input_run.id,
        "scope",
        "请补充讲解范围",
    )

    assert (
        await service.submit_input_answer(
            input_run.id,
            agent_input.input_key,
            "第二章",
            "other_user",
        )
        is None
    )
    assert agent_input.status == "pending"
    input_run.status = "running"
    assert (
        await service.submit_input_answer(
            input_run.id,
            agent_input.input_key,
            "第二章",
            "user_001",
        )
        is None
    )
    assert agent_input.status == "pending"

    approval_run = await service.create_run(
        user_id="user_001",
        thread_id="thread_001",
        workflow_name="plan",
        input_message="调整计划",
        parent_run_id=creation.run.id,
        root_run_id=creation.run.id,
        presentation="compact",
    )
    approval_run.status = "waiting_for_approval"
    approval = await service.create_approval(
        approval_run.id,
        "apply_learning_plan",
        '{"summary":"应用学习计划调整"}',
    )

    assert (
        await service.decide_approval(
            approval_run.id,
            approval.id,
            "approved",
            "other_user",
        )
        is None
    )
    assert approval.status == "pending"
    approval_run.status = "running"
    assert (
        await service.decide_approval(
            approval_run.id,
            approval.id,
            "approved",
            "user_001",
        )
        is None
    )
    assert approval.status == "pending"


@pytest.mark.asyncio
async def test_timeline_uses_sequence_cursor_for_pagination(db_session):
    await _create_thread(db_session)
    await _create_turn(db_session)
    await _create_turn(
        db_session,
        content="再给我三道练习题",
        client_message_id="client_002",
    )
    await _create_turn(
        db_session,
        content="再解释一下时间复杂度",
        client_message_id="client_003",
    )
    service = AgentTimelineService(db_session)

    latest = await service.get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=2,
    )
    earlier = await service.get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=latest.previous_cursor,
        limit=2,
    )

    assert [item["sequence"] for item in latest.items] == [2, 3]
    assert latest.previous_cursor == 2
    assert latest.latest_cursor == 3
    assert latest.has_more is True
    assert [item["sequence"] for item in earlier.items] == [1]
    assert earlier.previous_cursor is None
    assert earlier.has_more is False


@pytest.mark.asyncio
async def test_run_events_project_to_thread_cursor_and_assistant_message(db_session):
    await _create_thread(db_session)
    creation = await _create_turn(db_session)
    child = await AgentService(db_session).create_run(
        user_id="user_001",
        thread_id="thread_001",
        workflow_name="explain",
        input_message="解释循环队列",
        workflow_key="explain",
        workflow_version="v1",
        trigger_message_id=creation.message.id,
        parent_run_id=creation.run.id,
        root_run_id=creation.run.id,
        presentation="compact",
        public_title="整理讲解",
    )

    await event_store.append(
        db_session,
        child.id,
        "step.started",
        {"step_id": "step_public", "node_name": "generate_explanation"},
    )
    await event_store.append(
        db_session,
        child.id,
        "message.completed",
        {"content": "循环队列通过取模复用数组空间。"},
    )

    events = await thread_event_store.get_events(
        db_session,
        "thread_001",
        after_sequence=creation.timeline_cursor,
        limit=20,
    )
    assert [event.event_type for event in events] == [
        "workflow.updated",
        "workflow.step.updated",
        "timeline.item.created",
        "message.completed",
    ]
    assert events[1].payload["label"] == "组织讲解"
    assert "node_name" not in events[1].payload
    assert [event.sequence for event in events] == [2, 3, 4, 5]

    assistant = await db_session.scalar(
        select(AgentMessage).where(
            AgentMessage.run_id == child.id,
            AgentMessage.role == "assistant",
        )
    )
    assert assistant is not None
    assert assistant.status == "completed"
    assert assistant.content_text == "循环队列通过取模复用数组空间。"

    page = await AgentTimelineService(db_session).get_timeline(
        user_id="user_001",
        thread_id="thread_001",
        before=None,
        limit=50,
    )
    assert [item["type"] for item in page.items] == ["message", "message"]
    assert page.items[-1]["message"]["role"] == "assistant"
    assert page.latest_cursor == 5
