"""Memory bundle selectors for workflow consumers."""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.models.mysql_models import (
    CanonicalChapter,
    Chapter,
    Document,
    ExamOutline,
    KnowledgePoint,
    KnowledgePointChapterLink,
    Question,
    QuestionKnowledgeLink,
    Subject,
)
from app.modules.agent.memory_selector import (
    load_conversation_bundle,
    load_evaluation_bundle,
    load_planning_bundle,
    load_practice_bundle,
)
from app.modules.agent.models import (
    AgentArtifact, AgentConversationSummary,
    AgentMemoryItem,
    AgentMessage,
    AgentMemoryEvent,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentPreferenceCandidate,
    AgentRun,
    AgentThread,
    AgentThreadItem,
    UserLearningMastery,
)

SELECTOR_TABLES = [
    AgentThread.__table__,
    AgentMessage.__table__,
    AgentRun.__table__,
    AgentThreadItem.__table__,
    AgentArtifact.__table__,
    AgentMemoryEvent.__table__,
    AgentMemorySnapshot.__table__,
    AgentMemorySnapshotItem.__table__, AgentConversationSummary.__table__,
    AgentMemoryItem.__table__,
    AgentPreferenceCandidate.__table__,
    Subject.__table__,
    Chapter.__table__,
    # KnowledgePoint / CanonicalChapter 的可空外键在 SQLite 下也要求父表存在。
    ExamOutline.__table__,
    CanonicalChapter.__table__,
    Document.__table__,
    KnowledgePoint.__table__,
    KnowledgePointChapterLink.__table__,
    Question.__table__,
    QuestionKnowledgeLink.__table__,
    UserLearningMastery.__table__,
]


@pytest.mark.asyncio
async def test_load_planning_bundle_uses_approved_goals_and_real_weak_mastery(
    db_session,
):
    thread = AgentThread(
        id="thread_plan_bundle",
        user_id="user_001",
        title="规划",
        status="active",
    )
    run = AgentRun(
        id="run_plan_bundle",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="plan",
        status="queued",
        metadata_json={},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    await _seed_knowledge_point(
        db_session,
        kp_id="kp_graph",
        title="图的最短路径",
        aliases=["最短路"],
    )
    db_session.add_all(
        [
            AgentMemoryItem(
                id="memory_goal_001",
                user_id="user_001",
                scope="user",
                item_type="learning_goal",
                item_key="plan_confirmed:approval_001",
                status="active",
                content_text="二分查找计划",
                metadata_json={
                    "period": "14天",
                    "goals": [
                        {
                            "subject": "二分查找",
                            "target": "掌握边界条件",
                            "daily_minutes": 25,
                        }
                    ],
                },
            ),
            AgentMemoryItem(
                id="memory_goal_foreign",
                user_id="user_002",
                scope="user",
                item_type="learning_goal",
                item_key="plan_confirmed:approval_foreign",
                status="active",
                content_text="操作系统计划",
                metadata_json={
                    "goals": [{"subject": "操作系统", "target": "掌握调度"}]
                },
            ),
            UserLearningMastery(
                user_id="user_001",
                knowledge_point_id="kp_graph",
                mastery_score=0.4,
                evidence_count=2,
                correct_count=0,
                incorrect_count=2,
                last_evidence_id="grade_graph_001",
            ),
        ]
    )
    await db_session.flush()

    bundle = await load_planning_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )

    assert bundle.period == "14天"
    assert [target.title for target in bundle.targets] == [
        "二分查找",
        "图的最短路径",
    ]
    assert bundle.targets[0].target == "掌握边界条件"
    assert bundle.targets[0].daily_minutes == 25
    assert bundle.targets[1].source == "learning_mastery"
    assert bundle.targets[1].evidence_id == "grade_graph_001"
    assert "操作系统" not in [target.title for target in bundle.targets]


@pytest.mark.asyncio
async def test_load_planning_bundle_returns_no_targets_without_real_evidence(db_session):
    thread = AgentThread(
        id="thread_plan_empty",
        user_id="user_001",
        title="空规划",
        status="active",
    )
    run = AgentRun(
        id="run_plan_empty",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="plan",
        status="queued",
        metadata_json={},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()

    bundle = await load_planning_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )

    assert bundle.targets == []
    assert bundle.learning_goal_item_ids == []


@pytest.mark.asyncio
async def test_load_evaluation_bundle_uses_unique_snapshot_question_and_real_answer(
    db_session,
):
    thread = AgentThread(
        id="thread_evaluation_bundle",
        user_id="user_001",
        title="批改",
        status="active",
    )
    run = AgentRun(
        id="run_evaluation_bundle",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="grade",
        status="queued",
        input_message="我的答案是 B，请帮我批改",
        metadata_json={"memory_snapshot_id": "memsnap_evaluation_bundle"},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    await _seed_knowledge_point(
        db_session,
        kp_id="kp_binary_evaluation",
        title="二分查找",
        aliases=["折半查找"],
    )
    db_session.add(
        Question(
            id="question_evaluation_001",
            subject_id="subject_ds",
            type="choice",
            content="二分查找每轮将搜索区间缩小到多少？",
            options=[
                {"key": "A", "text": "四分之一"},
                {"key": "B", "text": "约一半"},
            ],
            answer="B",
            answer_source="manual",
            explanation="每轮排除约一半区间。",
            knowledge_point_ids=["kp_binary_evaluation"],
            review_status="approved",
            status="active",
        )
    )
    await db_session.flush()
    db_session.add(
        AgentMemorySnapshot(
            id="memsnap_evaluation_bundle",
            run_id=run.id,
            thread_id=thread.id,
            user_id="user_001",
            state_version=1,
            standalone_request="批改二分查找题的答案 B",
            understanding_json={
                "raw_input": "我的答案是 B，请帮我批改",
                "reference_sources": [
                    {
                        "type": "question",
                        "id": "question_evaluation_001",
                        "artifact_id": "artifact_practice_001",
                    }
                ],
            },
            selection_metadata_json={
                "selected_artifact_ids": ["artifact_practice_001"]
            },
        )
    )
    await db_session.flush()

    bundle = await load_evaluation_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )

    assert bundle.unresolved_reason is None
    assert bundle.user_answer == "B"
    assert bundle.question is not None
    assert bundle.question.id == "question_evaluation_001"
    assert bundle.question.standard_answer == "B"
    assert bundle.question.answer_source == "manual"
    assert bundle.question.knowledge_point_ids == ["kp_binary_evaluation"]
    assert bundle.question.source_artifact_id == "artifact_practice_001"


@pytest.mark.asyncio
async def test_load_evaluation_bundle_uses_generated_question_from_selected_artifact(
    db_session,
):
    thread = AgentThread(
        id="thread_generated_evaluation",
        user_id="user_001",
        title="模型题批改",
        status="active",
    )
    practice_run = AgentRun(
        id="run_generated_practice",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        status="completed",
    )
    grade_run = AgentRun(
        id="run_generated_grade",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="grade",
        status="queued",
        input_message="我的答案是 A",
        metadata_json={"memory_snapshot_id": "memsnap_generated_grade"},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add_all([practice_run, grade_run])
    await db_session.flush()
    practice_run.root_run_id = practice_run.id
    grade_run.root_run_id = grade_run.id
    db_session.add(
        AgentArtifact(
            id="artifact_generated_practice",
            run_id=practice_run.id,
            artifact_type="practice",
            content_json={
                "content": {
                    "question_ids": ["generated_run_generated_practice"],
                    "generated_questions": [
                        {
                            "id": "generated_run_generated_practice",
                            "question_type": "choice",
                            "content": "UDP 是否保证可靠交付？",
                            "options": [
                                {"key": "A", "text": "不保证"},
                                {"key": "B", "text": "保证"},
                            ],
                            "standard_answer": "A",
                            "answer_source": "llm",
                            "explanation": "UDP 不提供可靠交付保证。",
                        }
                    ],
                }
            },
        )
    )
    db_session.add(
        AgentMemorySnapshot(
            id="memsnap_generated_grade",
            run_id=grade_run.id,
            thread_id=thread.id,
            user_id="user_001",
            state_version=1,
            standalone_request="批改模型生成的 UDP 题",
            understanding_json={
                "raw_input": "我的答案是 A",
                "reference_sources": [
                    {
                        "type": "question",
                        "id": "generated_run_generated_practice",
                        "artifact_id": "artifact_generated_practice",
                    }
                ],
            },
            selection_metadata_json={
                "selected_artifact_ids": ["artifact_generated_practice"]
            },
        )
    )
    await db_session.flush()

    bundle = await load_evaluation_bundle(
        db_session,
        run_id=grade_run.id,
        user_id="user_001",
    )

    assert bundle.unresolved_reason is None
    assert bundle.user_answer == "A"
    assert bundle.question is not None
    assert bundle.question.id == "generated_run_generated_practice"
    assert bundle.question.standard_answer == "A"
    assert bundle.question.answer_source == "llm"


@pytest.mark.asyncio
async def test_load_evaluation_bundle_rejects_cross_user_snapshot_and_ambiguous_question(
    db_session,
):
    thread = AgentThread(
        id="thread_evaluation_guard",
        user_id="user_001",
        title="批改守卫",
        status="active",
    )
    run = AgentRun(
        id="run_evaluation_guard",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="grade",
        status="queued",
        input_message="我的答案是 A",
        metadata_json={"memory_snapshot_id": "memsnap_evaluation_foreign"},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    db_session.add(
        AgentMemorySnapshot(
            id="memsnap_evaluation_foreign",
            run_id=run.id,
            thread_id=thread.id,
            user_id="user_002",
            state_version=1,
            standalone_request="批改答案 A",
            understanding_json={
                "raw_input": "我的答案是 A",
                "reference_sources": [
                    {"type": "question", "id": "question_001"},
                    {"type": "question", "id": "question_002"},
                ],
            },
        )
    )
    await db_session.flush()

    foreign_bundle = await load_evaluation_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )
    assert foreign_bundle.unresolved_reason == "snapshot_not_found"

    snapshot = await db_session.get(
        AgentMemorySnapshot,
        "memsnap_evaluation_foreign",
    )
    snapshot.user_id = "user_001"
    await db_session.flush()
    ambiguous_bundle = await load_evaluation_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )
    assert ambiguous_bundle.unresolved_reason == "question_reference_ambiguous"


@pytest.mark.asyncio
async def test_load_conversation_bundle_replays_only_snapshot_selected_visible_context(
    db_session,
):
    thread = AgentThread(
        id="thread_conversation_bundle",
        user_id="user_001",
        title="讲解连续性",
        status="active",
    )
    run = AgentRun(
        id="run_conversation_bundle",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="explain",
        status="queued",
        input_message="再详细讲一下",
        metadata_json={"memory_snapshot_id": "snapshot_conversation_bundle"},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    messages = [
        AgentMessage(
            id="msg_selected_user",
            thread_id=thread.id,
            user_id="user_001",
            role="user",
            status="completed",
            content_text="什么是二分查找？",
        ),
        AgentMessage(
            id="msg_selected_assistant",
            thread_id=thread.id,
            user_id="user_001",
            role="assistant",
            status="completed",
            content_text="它每轮排除一半区间。",
        ),
        AgentMessage(
            id="msg_hidden",
            thread_id=thread.id,
            user_id="user_001",
            role="user",
            status="completed",
            content_text="隐藏消息不得进入模型",
        ),
    ]
    db_session.add_all(messages)
    await db_session.flush()
    db_session.add_all(
        [
            AgentThreadItem(
                id=f"item_{message.id}",
                thread_id=thread.id,
                sequence=index,
                item_type="message",
                ref_id=message.id,
                visibility="hidden" if message.id == "msg_hidden" else "visible",
            )
            for index, message in enumerate(messages, start=1)
        ]
    )
    artifact = AgentArtifact(
        id="artifact_conversation_bundle",
        run_id=run.id,
        artifact_type="explanation",
        content_json={"summary": "二分查找基础讲解"},
    )
    db_session.add(artifact)
    summary = AgentConversationSummary(
        id="convsum_conversation_bundle",
        thread_id=thread.id,
        user_id="user_001",
        start_sequence=1,
        end_sequence=2,
        summary_text="当前版本可能已经变化，但 Explain 必须使用 snapshot 副本。",
        source_message_ids_json=["msg_old_user", "msg_old_assistant"],
        version=3,
    )
    db_session.add(summary)
    await db_session.flush()
    db_session.add(
        AgentMemorySnapshot(
            id="snapshot_conversation_bundle",
            run_id=run.id,
            thread_id=thread.id,
            user_id="user_001",
            state_version=1,
            standalone_request="给用户详细讲解二分查找",
            understanding_json={
                "topic_entities": [
                    {
                        "entity_type": "knowledge_point",
                        "entity_id": "kp_binary_search",
                        "title": "二分查找",
                        "aliases": ["折半查找"],
                        "source": "thread_memory",
                    }
                ],
                "reference_sources": [],
            },
            selection_metadata_json={
                "selected_message_ids": [
                    "msg_selected_user",
                    "msg_selected_assistant",
                    "msg_hidden",
                ],
                "selected_artifact_ids": [artifact.id],
                "conversation_summary_id": summary.id,
            },
        )
    )
    await db_session.flush()
    db_session.add(
        AgentMemorySnapshotItem(
            snapshot_id="snapshot_conversation_bundle",
            memory_need="conversation_continuity",
            memory_partition="historical_summaries",
            source_kind="conversation_summary",
            source_id=summary.id,
            item_key=summary.id,
            version=3,
            selected=True,
            selection_reason="active_summary_before_recent_history",
            token_estimate=10,
            payload_json={
                "summary_text": "用户此前在复习二分查找，并希望继续理解边界条件。",
                "start_sequence": 1,
                "end_sequence": 2,
                "source_message_ids": ["msg_old_user", "msg_old_assistant"],
            },
        )
    )
    await db_session.flush()

    bundle = await load_conversation_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )

    assert [message.message_id for message in bundle.messages] == [
        "msg_selected_user",
        "msg_selected_assistant",
    ]
    assert bundle.artifact_summaries == ["二分查找基础讲解"]
    assert bundle.conversation_summary == (
        "用户此前在复习二分查找，并希望继续理解边界条件。"
    )
    assert bundle.conversation_summary_id == summary.id
    assert bundle.conversation_summary_version == 3
    assert bundle.retrieval_query == "二分查找 折半查找"
    assert bundle.standalone_request == "给用户详细讲解二分查找"
    assert len(bundle.to_message_history()) == 2

    summary.version = 4
    await db_session.flush()
    version_mismatch_bundle = await load_conversation_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )
    assert version_mismatch_bundle.conversation_summary is None

    summary.version = 3
    db_session.add(
        AgentMemorySnapshotItem(
            snapshot_id="snapshot_conversation_bundle",
            memory_need="conversation_continuity",
            memory_partition="historical_summaries",
            source_kind="conversation_summary",
            source_id=summary.id,
            item_key="duplicate_conversation_summary",
            version=3,
            selected=True,
            payload_json={"summary_text": "重复条目不能静默进入 Explain。"},
        )
    )
    await db_session.flush()
    duplicate_bundle = await load_conversation_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )
    assert duplicate_bundle.conversation_summary is None


_chapter_link_id = 0


async def _seed_chapter_link(
    db_session,
    *,
    kp_id: str,
    chapter_id: str,
    chapter_name: str,
    is_primary: bool,
    relevance: float,
) -> None:
    # BigInteger 主键在 SQLite 下不自增，测试里显式分配。
    global _chapter_link_id
    _chapter_link_id += 1
    chapter = await db_session.get(CanonicalChapter, chapter_id)
    if chapter is None:
        db_session.add(
            CanonicalChapter(id=chapter_id, subject_id="subject_ds", name=chapter_name)
        )
        await db_session.flush()
    db_session.add(
        KnowledgePointChapterLink(
            id=_chapter_link_id,
            knowledge_point_id=kp_id,
            canonical_chapter_id=chapter_id,
            is_primary=is_primary,
            relevance=relevance,
        )
    )
    await db_session.flush()


async def _seed_knowledge_point(
    db_session,
    *,
    kp_id: str,
    title: str,
    aliases: list[str],
) -> None:
    subject = await db_session.get(Subject, "subject_ds")
    if subject is None:
        db_session.add(Subject(id="subject_ds", name="数据结构", code="ds"))
        await db_session.flush()
        db_session.add(Chapter(id="chapter_ds_01", subject_id="subject_ds", name="查找"))
        await db_session.flush()
    db_session.add(
        KnowledgePoint(
            id=kp_id,
            chapter_id="chapter_ds_01",
            subject_id="subject_ds",
            title=title,
            content=f"{title}正文",
            aliases=aliases,
        )
    )
    await db_session.flush()


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=SELECTOR_TABLES,
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_load_practice_bundle_uses_snapshot_topic_and_context_metadata(db_session):
    thread = AgentThread(
        id="thread_001",
        user_id="user_001",
        title="练习题线程",
        status="active",
    )
    run = AgentRun(
        id="run_validate_001",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        workflow_key="validate",
        workflow_version="v1",
        status="queued",
        input_message="给我出道题",
        metadata_json={
            "memory_snapshot_id": "memsnap_001",
        },
        created_at=datetime(2026, 7, 26, 20, 0, 0),
    )
    snapshot = AgentMemorySnapshot(
        id="memsnap_001",
        run_id=run.id,
        thread_id=thread.id,
        user_id="user_001",
        state_version=4,
        standalone_request="给用户出一道关于二分查找的练习题",
        understanding_json={
            "raw_input": "给我出道题",
            "standalone_request": "给用户出一道关于二分查找的练习题",
            "intent_hint": "practice_generation",
            "topic_entities": [
                {
                    "entity_type": "knowledge_point",
                    "entity_id": "kp_binary_search",
                    "title": "二分查找",
                    "source": "thread_memory",
                    "aliases": ["折半查找"],
                }
            ],
            "constraints": ["难度适中"],
            "reference_sources": [{"type": "knowledge_point", "id": "kp_binary_search"}],
        },
        selection_metadata_json={
            "selected_message_ids": ["msg_001"],
            "selected_artifact_ids": ["artifact_001", "artifact_002"],
        },
    )
    snapshot_item = AgentMemorySnapshotItem(
        snapshot_id=snapshot.id,
        memory_need="topic_focus",
        memory_partition="current_turn_understanding",
        source_kind="message",
        source_id="msg_001",
        item_key="msg_001",
        version=4,
        selected=True,
        selection_reason="current_turn_understanding",
        token_estimate=8,
        payload_json={"title": "二分查找"},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    db_session.add(snapshot)
    await db_session.flush()
    db_session.add(snapshot_item)
    await db_session.flush()
    # 即使存在唯一薄弱点，快照主题也必须优先，不触发掌握度回退。
    db_session.add(
        UserLearningMastery(
            user_id="user_001",
            subject_id="subject_ds",
            knowledge_point_id="kp_red_black_tree",
            mastery_score=0.2,
            evidence_count=3,
            correct_count=1,
            incorrect_count=2,
        )
    )
    await db_session.flush()
    # 知识点挂载两个标准章节：主章节应排在关联章节前面。
    await _seed_knowledge_point(
        db_session,
        kp_id="kp_binary_search",
        title="二分查找",
        aliases=["折半查找"],
    )
    await _seed_chapter_link(
        db_session,
        kp_id="kp_binary_search",
        chapter_id="cchap_algo_basic",
        chapter_name="算法基础",
        is_primary=False,
        relevance=0.6,
    )
    await _seed_chapter_link(
        db_session,
        kp_id="kp_binary_search",
        chapter_id="cchap_search",
        chapter_name="查找",
        is_primary=True,
        relevance=1.0,
    )

    bundle = await load_practice_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )

    assert bundle.snapshot_id == "memsnap_001"
    assert bundle.standalone_request == "给用户出一道关于二分查找的练习题"
    assert bundle.topic is not None
    assert bundle.topic.title == "二分查找"
    assert bundle.topic.aliases == ["折半查找"]
    assert bundle.constraints == ["难度适中"]
    assert bundle.difficulty == "medium"
    assert bundle.knowledge_point_ids == ["kp_binary_search"]
    assert bundle.chapter_ids == ["cchap_search", "cchap_algo_basic"]
    assert bundle.chapter_scope_source == "knowledge_point"
    assert bundle.selected_artifact_ids == ["artifact_001", "artifact_002"]
    assert bundle.excluded_question_ids == []
    assert bundle.topic.source == "thread_memory"
    assert bundle.mastery_signals == []


@pytest.mark.asyncio
async def test_explicit_chapter_ordinal_overrides_knowledge_point_default_chapters(
    db_session,
):
    thread = AgentThread(
        id="thread_explicit_chapter",
        user_id="user_001",
        title="显式章节约束",
        status="active",
    )
    run = AgentRun(
        id="run_explicit_chapter",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        workflow_key="validate",
        workflow_version="v1",
        status="queued",
        input_message="给我出一道第三章的题",
        metadata_json={"memory_snapshot_id": "memsnap_explicit_chapter"},
    )
    snapshot = AgentMemorySnapshot(
        id="memsnap_explicit_chapter",
        run_id=run.id,
        thread_id=thread.id,
        user_id="user_001",
        state_version=1,
        standalone_request="给用户出一道关于二分查找的练习题",
        understanding_json={
            "raw_input": "给我出一道第三章的题",
            "standalone_request": "给用户出一道关于二分查找的练习题",
            "intent_hint": "practice_generation",
            "topic_entities": [
                {
                    "entity_type": "knowledge_point",
                    "entity_id": "kp_binary_search",
                    "title": "二分查找",
                    "source": "thread_memory",
                    "aliases": ["折半查找"],
                }
            ],
            "constraints": ["chapter_ordinal:3"],
            "reference_sources": [],
        },
        selection_metadata_json={},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    db_session.add(snapshot)
    await db_session.flush()
    await _seed_knowledge_point(
        db_session,
        kp_id="kp_binary_search",
        title="二分查找",
        aliases=["折半查找"],
    )
    db_session.add_all(
        [
            CanonicalChapter(
                id="cchap_ds_01",
                subject_id="subject_ds",
                level=1,
                name="绪论",
                sort_order=0,
                status="active",
            ),
            CanonicalChapter(
                id="cchap_ds_02",
                subject_id="subject_ds",
                level=1,
                name="线性表",
                sort_order=1,
                status="active",
            ),
            CanonicalChapter(
                id="cchap_ds_03",
                subject_id="subject_ds",
                level=1,
                name="栈、队列和数组",
                sort_order=2,
                status="active",
            ),
        ]
    )
    await db_session.flush()
    await _seed_chapter_link(
        db_session,
        kp_id="kp_binary_search",
        chapter_id="cchap_search_default",
        chapter_name="查找",
        is_primary=True,
        relevance=1.0,
    )
    default_chapter = await db_session.get(CanonicalChapter, "cchap_search_default")
    default_chapter.sort_order = 9
    await db_session.flush()

    bundle = await load_practice_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )

    assert bundle.constraints == ["chapter_ordinal:3"]
    assert bundle.knowledge_point_ids == ["kp_binary_search"]
    assert bundle.chapter_ids == ["cchap_ds_03"]
    assert bundle.chapter_scope_source == "explicit"


async def _create_run_without_snapshot(db_session, *, run_id: str) -> AgentRun:
    thread = AgentThread(
        id=f"thread_{run_id}",
        user_id="user_001",
        title="薄弱点回退线程",
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
        input_message="给我出道题",
        metadata_json={},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    return run


@pytest.mark.asyncio
async def test_load_practice_bundle_falls_back_to_unique_weak_point(db_session):
    run = await _create_run_without_snapshot(db_session, run_id="run_weak_unique")
    await _seed_knowledge_point(
        db_session,
        kp_id="kp_red_black_tree",
        title="红黑树",
        aliases=["RB树"],
    )
    await _seed_chapter_link(
        db_session,
        kp_id="kp_red_black_tree",
        chapter_id="cchap_tree",
        chapter_name="树",
        is_primary=True,
        relevance=1.0,
    )
    db_session.add_all(
        [
            UserLearningMastery(
                user_id="user_001",
                subject_id="subject_ds",
                knowledge_point_id="kp_red_black_tree",
                mastery_score=0.3,
                evidence_count=4,
                correct_count=1,
                incorrect_count=3,
                last_evidence_id="grade_evidence_001",
            ),
            # 高掌握度知识点不参与薄弱点回退。
            UserLearningMastery(
                user_id="user_001",
                subject_id="subject_ds",
                knowledge_point_id="kp_binary_search",
                mastery_score=0.9,
                evidence_count=10,
                correct_count=9,
                incorrect_count=1,
            ),
            # 没有真实评分证据的低分行不允许触发回退。
            UserLearningMastery(
                user_id="user_001",
                subject_id="subject_ds",
                knowledge_point_id="kp_avl_tree",
                mastery_score=0.1,
                evidence_count=0,
            ),
        ]
    )
    await db_session.flush()

    bundle = await load_practice_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )

    assert bundle.topic is not None
    assert bundle.topic.title == "红黑树"
    assert bundle.topic.aliases == ["RB树"]
    assert bundle.topic.source == "learning_mastery"
    assert bundle.knowledge_point_ids == ["kp_red_black_tree"]
    assert bundle.chapter_ids == ["cchap_tree"]
    assert len(bundle.mastery_signals) == 1
    signal = bundle.mastery_signals[0]
    assert signal["knowledge_point_id"] == "kp_red_black_tree"
    assert signal["mastery_score"] == 0.3
    assert signal["raw_mastery_score"] == 0.3
    assert signal["effective_mastery_score"] == 0.3
    assert signal["evidence_count"] == 4
    assert signal["last_evidence_id"] == "grade_evidence_001"
    assert signal["decay_policy_version"] == "mastery-decay-v1"


@pytest.mark.asyncio
async def test_load_practice_bundle_skips_weak_point_when_multiple_candidates(db_session):
    run = await _create_run_without_snapshot(db_session, run_id="run_weak_multi")
    await _seed_knowledge_point(
        db_session,
        kp_id="kp_red_black_tree",
        title="红黑树",
        aliases=[],
    )
    db_session.add_all(
        [
            UserLearningMastery(
                user_id="user_001",
                subject_id="subject_ds",
                knowledge_point_id="kp_red_black_tree",
                mastery_score=0.3,
                evidence_count=4,
            ),
            UserLearningMastery(
                user_id="user_001",
                subject_id="subject_ds",
                knowledge_point_id="kp_binary_search",
                mastery_score=0.4,
                evidence_count=2,
            ),
        ]
    )
    await db_session.flush()

    bundle = await load_practice_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
    )

    # 多个薄弱点无法确定唯一回退主题，维持澄清路径。
    assert bundle.topic is None
    assert bundle.mastery_signals == []
    assert bundle.knowledge_point_ids == []


@pytest.mark.asyncio
async def test_load_practice_bundle_excludes_recent_practice_questions(db_session):
    thread = AgentThread(
        id="thread_002",
        user_id="user_001",
        title="排除集线程",
        status="active",
    )
    old_run = AgentRun(
        id="run_validate_old",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        workflow_key="validate",
        workflow_version="v1",
        status="completed",
        input_message="给我出道题",
    )
    new_run = AgentRun(
        id="run_validate_new",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        workflow_key="validate",
        workflow_version="v1",
        status="queued",
        input_message="再出一道",
        metadata_json={},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add_all([old_run, new_run])
    await db_session.flush()
    db_session.add_all(
        [
            AgentMemoryEvent(
                user_id="user_001",
                thread_id=thread.id,
                run_id=old_run.id,
                memory_scope="user",
                source_kind="artifact",
                fact_type="practice_artifact_created",
                idempotency_key="practice_artifact_created:run_validate_older",
                payload_json={
                    "artifact_id": "art_older",
                    "question_ids": ["question_001", "question_002"],
                },
            ),
            AgentMemoryEvent(
                user_id="user_001",
                thread_id=thread.id,
                run_id=old_run.id,
                memory_scope="user",
                source_kind="artifact",
                fact_type="practice_artifact_created",
                idempotency_key="practice_artifact_created:run_validate_old",
                payload_json={
                    "artifact_id": "art_old",
                    "question_ids": ["question_002", "question_003"],
                },
            ),
            AgentMemoryEvent(
                user_id="user_other",
                thread_id=None,
                run_id=None,
                memory_scope="user",
                source_kind="artifact",
                fact_type="practice_artifact_created",
                idempotency_key="practice_artifact_created:run_other_user",
                payload_json={
                    "artifact_id": "art_other",
                    "question_ids": ["question_999"],
                },
            ),
        ]
    )
    await db_session.flush()

    bundle = await load_practice_bundle(
        db_session,
        run_id=new_run.id,
        user_id="user_001",
    )

    # 最新事件的题排在最前，跨事件重复的题只保留一次，其他用户的题不进入排除集。
    assert bundle.excluded_question_ids == [
        "question_002",
        "question_003",
        "question_001",
    ]


@pytest.mark.asyncio
async def test_explicit_repeat_removes_only_unique_referenced_question_from_exclusions(
    db_session,
):
    thread = AgentThread(
        id="thread_repeat_question",
        user_id="user_001",
        title="重复题目线程",
        status="active",
    )
    old_run = AgentRun(
        id="run_repeat_question_old",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        status="completed",
        input_message="给我出道题",
    )
    repeat_run = AgentRun(
        id="run_repeat_question_new",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        status="queued",
        input_message="再出一遍上次那道题",
        metadata_json={"memory_snapshot_id": "snapshot_repeat_question"},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add_all([old_run, repeat_run])
    await db_session.flush()
    snapshot = AgentMemorySnapshot(
        id="snapshot_repeat_question",
        run_id=repeat_run.id,
        thread_id=thread.id,
        user_id="user_001",
        state_version=1,
        standalone_request="再次生成用户明确引用的题目",
        understanding_json={
            "constraints": ["repeat_referenced_question"],
            "reference_sources": [
                {"type": "question", "id": "question_repeat"}
            ],
        },
        selection_metadata_json={},
    )
    db_session.add_all(
        [
            snapshot,
            AgentMemoryEvent(
                user_id="user_001",
                thread_id=thread.id,
                run_id=old_run.id,
                memory_scope="user",
                source_kind="artifact",
                fact_type="practice_artifact_created",
                idempotency_key="practice_artifact_created:repeat_question_old",
                payload_json={
                    "artifact_id": "artifact_repeat_question_old",
                    "question_ids": ["question_repeat", "question_other"],
                },
            ),
        ]
    )
    await db_session.flush()

    bundle = await load_practice_bundle(
        db_session,
        run_id=repeat_run.id,
        user_id="user_001",
    )

    assert bundle.excluded_question_ids == ["question_other"]

    snapshot.understanding_json = {
        **snapshot.understanding_json,
        "reference_sources": [
            {"type": "question", "id": "question_repeat"},
            {"type": "question", "id": "question_other"},
        ],
    }
    await db_session.flush()
    ambiguous_bundle = await load_practice_bundle(
        db_session,
        run_id=repeat_run.id,
        user_id="user_001",
    )
    assert ambiguous_bundle.excluded_question_ids == [
        "question_repeat",
        "question_other",
    ]


@pytest.mark.asyncio
async def test_practice_uses_decayed_mastery_and_freezes_it_per_snapshot(db_session):
    from datetime import timedelta
    from sqlalchemy import select

    now = datetime(2026, 7, 27, 8, 0, 0)
    thread = AgentThread(
        id="thread_mastery_decay_practice",
        user_id="user_001",
        title="掌握度衰减练习",
        status="active",
    )
    run = AgentRun(
        id="run_mastery_decay_practice",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        status="queued",
        metadata_json={"memory_snapshot_id": "snapshot_mastery_decay_practice"},
    )
    snapshot = AgentMemorySnapshot(
        id="snapshot_mastery_decay_practice",
        run_id=run.id,
        thread_id=thread.id,
        user_id="user_001",
        state_version=1,
        standalone_request="给我出道题",
        understanding_json={"topic_entities": [], "constraints": []},
        selection_metadata_json={},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    db_session.add(snapshot)
    await db_session.flush()
    await _seed_knowledge_point(
        db_session,
        kp_id="kp_mastery_decay_practice",
        title="散列表冲突处理",
        aliases=["哈希冲突"],
    )
    mastery = UserLearningMastery(
        user_id="user_001",
        subject_id="subject_ds",
        knowledge_point_id="kp_mastery_decay_practice",
        mastery_score=1.0,
        evidence_count=1,
        correct_count=1,
        incorrect_count=0,
        last_evidence_id="grade_stale_001",
        last_graded_at=now - timedelta(days=180),
    )
    db_session.add_all(
        [
            mastery,
            UserLearningMastery(
                user_id="user_002",
                subject_id="subject_ds",
                knowledge_point_id="kp_mastery_decay_practice",
                mastery_score=0.0,
                evidence_count=5,
                last_graded_at=now - timedelta(days=365),
            ),
        ]
    )
    await db_session.flush()

    stale_bundle = await load_practice_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
        now=now,
    )

    assert stale_bundle.topic is not None
    assert stale_bundle.topic.title == "散列表冲突处理"
    assert len(stale_bundle.mastery_signals) == 1
    frozen_signal = stale_bundle.mastery_signals[0]
    assert frozen_signal["raw_mastery_score"] == 1.0
    assert frozen_signal["effective_mastery_score"] == 0.4
    assert frozen_signal["mastery_score"] == 0.4
    assert frozen_signal["age_days"] == 180
    frozen_items = list(
        (
            await db_session.execute(
                select(AgentMemorySnapshotItem).where(
                    AgentMemorySnapshotItem.snapshot_id == snapshot.id,
                    AgentMemorySnapshotItem.memory_need == "practice_generation",
                    AgentMemorySnapshotItem.memory_partition == "learning_mastery",
                )
            )
        ).scalars()
    )
    assert len(frozen_items) == 1
    assert frozen_items[0].payload_json == frozen_signal

    mastery.mastery_score = 1.0
    mastery.evidence_count = 2
    mastery.last_evidence_id = "grade_fresh_002"
    mastery.last_graded_at = now
    knowledge_point = await db_session.get(
        KnowledgePoint,
        "kp_mastery_decay_practice",
    )
    knowledge_point.title = "散列表冲突处理（新标题）"
    knowledge_point.aliases = ["哈希冲突新别名"]
    await db_session.flush()
    replayed_bundle = await load_practice_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
        now=now,
    )
    assert replayed_bundle.mastery_signals == [frozen_signal]
    assert replayed_bundle.topic is not None
    assert replayed_bundle.topic.title == "散列表冲突处理"
    assert replayed_bundle.topic.aliases == ["哈希冲突"]
    replayed_items = list(
        (
            await db_session.execute(
                select(AgentMemorySnapshotItem).where(
                    AgentMemorySnapshotItem.snapshot_id == snapshot.id,
                    AgentMemorySnapshotItem.memory_need == "practice_generation",
                    AgentMemorySnapshotItem.memory_partition == "learning_mastery",
                )
            )
        ).scalars()
    )
    assert len(replayed_items) == 1

    fresh_run = AgentRun(
        id="run_mastery_fresh_practice",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="validate",
        status="queued",
        metadata_json={"memory_snapshot_id": "snapshot_mastery_fresh_practice"},
    )
    db_session.add(fresh_run)
    await db_session.flush()
    db_session.add(
        AgentMemorySnapshot(
            id="snapshot_mastery_fresh_practice",
            run_id=fresh_run.id,
            thread_id=thread.id,
            user_id="user_001",
            state_version=2,
            standalone_request="再给我出道题",
            understanding_json={"topic_entities": [], "constraints": []},
            selection_metadata_json={},
        )
    )
    await db_session.flush()

    fresh_bundle = await load_practice_bundle(
        db_session,
        run_id=fresh_run.id,
        user_id="user_001",
        now=now,
    )
    assert fresh_bundle.topic is None
    assert fresh_bundle.mastery_signals == []


@pytest.mark.asyncio
async def test_planning_uses_the_same_effective_mastery_policy(db_session):
    from datetime import timedelta
    from sqlalchemy import select

    now = datetime(2026, 7, 27, 8, 0, 0)
    thread = AgentThread(
        id="thread_mastery_decay_plan",
        user_id="user_001",
        title="掌握度衰减计划",
        status="active",
    )
    run = AgentRun(
        id="run_mastery_decay_plan",
        thread_id=thread.id,
        user_id="user_001",
        workflow_name="plan",
        status="queued",
        metadata_json={"memory_snapshot_id": "snapshot_mastery_decay_plan"},
    )
    snapshot = AgentMemorySnapshot(
        id="snapshot_mastery_decay_plan",
        run_id=run.id,
        thread_id=thread.id,
        user_id="user_001",
        state_version=1,
        standalone_request="制定复习计划",
        understanding_json={"topic_entities": []},
        selection_metadata_json={},
    )
    db_session.add(thread)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    db_session.add(snapshot)
    await db_session.flush()
    await _seed_knowledge_point(
        db_session,
        kp_id="kp_mastery_decay_plan",
        title="最小生成树",
        aliases=["MST"],
    )
    db_session.add(
        UserLearningMastery(
            user_id="user_001",
            subject_id="subject_ds",
            knowledge_point_id="kp_mastery_decay_plan",
            mastery_score=1.0,
            evidence_count=3,
            correct_count=3,
            incorrect_count=0,
            last_evidence_id="grade_plan_stale",
            last_graded_at=now - timedelta(days=180),
        )
    )
    await db_session.flush()

    bundle = await load_planning_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
        now=now,
    )

    assert len(bundle.mastery_signals) == 1
    assert bundle.mastery_signals[0]["effective_mastery_score"] == 0.4
    assert bundle.targets[0].title == "最小生成树"
    assert bundle.targets[0].mastery_score == 0.4
    frozen_item = await db_session.scalar(
        select(AgentMemorySnapshotItem).where(
            AgentMemorySnapshotItem.snapshot_id == snapshot.id,
            AgentMemorySnapshotItem.memory_need == "planning_goal",
            AgentMemorySnapshotItem.memory_partition == "learning_mastery",
        )
    )
    assert frozen_item is not None
    assert frozen_item.payload_json == bundle.mastery_signals[0]

    knowledge_point = await db_session.get(
        KnowledgePoint,
        "kp_mastery_decay_plan",
    )
    knowledge_point.title = "最小生成树（新标题）"
    await db_session.flush()
    replayed = await load_planning_bundle(
        db_session,
        run_id=run.id,
        user_id="user_001",
        now=now,
    )
    assert replayed.targets[0].title == "最小生成树"
    assert replayed.mastery_signals == bundle.mastery_signals
