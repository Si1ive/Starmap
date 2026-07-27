"""TurnUnderstanding 的确定性主题、约束与结构化指代测试。"""

from datetime import datetime

from app.modules.agent.context_builder import (
    AgentRunContext,
    ArtifactContext,
    PermissionScope,
)
from app.modules.agent.turn_understanding import (
    build_ambiguous_referent_candidates,
    build_turn_understanding,
)


def _context(
    *,
    current_input: str,
    active_topic: dict | None = None,
    recent_artifacts: list[ArtifactContext] | None = None,
    context_refs: list[dict] | None = None,
) -> AgentRunContext:
    return AgentRunContext(
        thread_id="thread_001",
        user_id="user_001",
        turn_id="run_001",
        current_message_id="msg_001",
        current_input=current_input,
        active_topic=active_topic,
        recent_artifacts=recent_artifacts or [],
        context_refs=context_refs or [],
        permission_scope=PermissionScope(
            user_id="user_001",
            thread_id="thread_001",
            root_run_id="run_001",
        ),
        token_budget=4096,
        history_token_budget=2048,
        estimated_tokens=32,
    )


def _practice_artifact(
    artifact_id: str,
    *question_ids: str,
) -> ArtifactContext:
    return ArtifactContext(
        id=artifact_id,
        run_id=f"run_{artifact_id}",
        artifact_type="practice",
        summary="练习题摘要里没有可信题目 ID",
        created_at=datetime(2026, 7, 26, 10, 0),
        estimated_tokens=10,
        reference_entities=[
            {
                "type": "question",
                "id": question_id,
                "source": "artifact",
                "artifact_id": artifact_id,
            }
            for question_id in question_ids
        ],
    )


def test_build_turn_understanding_preserves_topic_aliases_and_difficulty_constraint():
    understanding = build_turn_understanding(
        _context(
            current_input="给我出一道难一点的题",
            active_topic={
                "entity_type": "knowledge_point",
                "entity_id": "kp_binary_search",
                "title": "二分查找",
                "aliases": ["折半查找"],
                "source": "thread_memory",
            },
        )
    )

    assert understanding.standalone_request == "给用户出一道关于二分查找的练习题"
    assert understanding.intent_hint == "practice_generation"
    assert understanding.topic_entities[0].aliases == ["折半查找"]
    assert understanding.constraints == ["difficulty:hard"]


def test_build_turn_understanding_extracts_explicit_chapter_ordinal():
    understanding = build_turn_understanding(
        _context(
            current_input="给我出一道第三章难一点的题",
            active_topic={
                "entity_type": "knowledge_point",
                "entity_id": "kp_binary_search",
                "title": "二分查找",
                "aliases": ["折半查找"],
                "source": "thread_memory",
            },
        )
    )

    assert understanding.standalone_request == "给用户出一道关于二分查找的练习题"
    assert understanding.constraints == ["difficulty:hard", "chapter_ordinal:3"]


def test_build_turn_understanding_resolves_previous_single_question_from_latest_artifact():
    understanding = build_turn_understanding(
        _context(
            current_input="再讲一下上一道题",
            recent_artifacts=[
                _practice_artifact("artifact_practice", "question_001")
            ],
        )
    )

    assert understanding.reference_sources == [
        {
            "type": "question",
            "id": "question_001",
            "source": "artifact",
            "artifact_id": "artifact_practice",
        }
    ]
    assert build_ambiguous_referent_candidates(
        _context(
            current_input="再讲一下上一道题",
            recent_artifacts=[
                _practice_artifact("artifact_practice", "question_001")
            ],
        ),
        understanding,
    ) == []


def test_build_turn_understanding_keeps_multiple_previous_questions_ambiguous():
    understanding = build_turn_understanding(
        _context(
            current_input="上一道题再讲一下",
            recent_artifacts=[
                _practice_artifact(
                    "artifact_practice",
                    "question_001",
                    "question_002",
                )
            ],
        )
    )

    assert understanding.reference_sources == []


def test_build_turn_understanding_does_not_fall_back_past_newer_ambiguous_practice():
    understanding = build_turn_understanding(
        _context(
            current_input="这道题再解释一下",
            recent_artifacts=[
                _practice_artifact("artifact_old", "question_old"),
                _practice_artifact(
                    "artifact_new",
                    "question_new_001",
                    "question_new_002",
                ),
            ],
        )
    )

    assert understanding.reference_sources == []


def test_build_turn_understanding_never_guesses_question_id_from_artifact_summary():
    artifact = _practice_artifact("artifact_practice")
    artifact.summary = "上一道题是 question_from_summary"

    understanding = build_turn_understanding(
        _context(
            current_input="再讲一下上一道题",
            recent_artifacts=[artifact],
        )
    )

    assert understanding.reference_sources == []


def test_explicit_reference_prevents_bare_referent_model_candidates():
    context = _context(
        current_input="这个再讲一下",
        context_refs=[
            {
                "type": "question",
                "id": "question_explicit",
                "title": "用户显式选中的题",
            }
        ],
        recent_artifacts=[
            _practice_artifact(
                "artifact_practice",
                "question_001",
                "question_002",
            )
        ],
    )
    understanding = build_turn_understanding(context)

    assert build_ambiguous_referent_candidates(context, understanding) == []


def test_explicit_repeat_marks_unique_previous_question_for_exclusion_override():
    understanding = build_turn_understanding(
        _context(
            current_input="再出一遍上次那道题",
            active_topic={
                "entity_type": "knowledge_point",
                "entity_id": "kp_binary_search",
                "title": "二分查找",
            },
            recent_artifacts=[
                _practice_artifact("artifact_practice", "question_001")
            ],
        )
    )

    assert understanding.intent_hint == "practice_generation"
    assert understanding.constraints == ["repeat_referenced_question"]
    assert understanding.reference_sources[-1]["id"] == "question_001"


def test_negative_repeat_phrase_does_not_relax_exclusion_policy():
    understanding = build_turn_understanding(
        _context(
            current_input="不要再出上次那道题",
            recent_artifacts=[
                _practice_artifact("artifact_practice", "question_001")
            ],
        )
    )

    assert "repeat_referenced_question" not in understanding.constraints
