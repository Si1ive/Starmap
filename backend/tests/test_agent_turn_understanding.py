"""TurnUnderstanding 的确定性主题与约束提取测试。"""

from app.modules.agent.context_builder import AgentRunContext, PermissionScope
from app.modules.agent.turn_understanding import build_turn_understanding


def _context(*, current_input: str, active_topic: dict | None = None) -> AgentRunContext:
    return AgentRunContext(
        thread_id="thread_001",
        user_id="user_001",
        turn_id="run_001",
        current_message_id="msg_001",
        current_input=current_input,
        active_topic=active_topic,
        permission_scope=PermissionScope(
            user_id="user_001",
            thread_id="thread_001",
            root_run_id="run_001",
        ),
        token_budget=4096,
        history_token_budget=2048,
        estimated_tokens=32,
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
