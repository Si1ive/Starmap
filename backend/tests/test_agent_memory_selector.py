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
    load_evaluation_bundle,
    load_planning_bundle,
    load_practice_bundle,
)
from app.modules.agent.models import (
    AgentMemoryItem,
    AgentMessage,
    AgentMemoryEvent,
    AgentMemorySnapshot,
    AgentMemorySnapshotItem,
    AgentRun,
    AgentThread,
    UserLearningMastery,
)

SELECTOR_TABLES = [
    AgentThread.__table__,
    AgentMessage.__table__,
    AgentRun.__table__,
    AgentMemoryEvent.__table__,
    AgentMemorySnapshot.__table__,
    AgentMemorySnapshotItem.__table__,
    AgentMemoryItem.__table__,
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
    assert bundle.mastery_signals == [
        {
            "knowledge_point_id": "kp_red_black_tree",
            "mastery_score": 0.3,
            "evidence_count": 4,
            "last_evidence_id": "grade_evidence_001",
        }
    ]


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
