"""Agent memory contracts stay workflow-neutral and partitioned."""

from app.modules.agent.memory_contracts import (
    MEMORY_NEED_PARTITIONS,
    MemoryNeed,
    MemoryPartition,
)


def test_memory_partitions_cover_the_planned_foundation():
    assert {partition.value for partition in MemoryPartition} == {
        "current_turn_understanding",
        "thread_topic_state",
        "recent_conversation",
        "topic_summary",
        "learning_mastery",
        "learning_weakness",
        "learning_hypothesis",
        "artifact_and_task",
        "pending_interaction",
        "user_preference",
        "user_goal",
    }


def test_memory_needs_use_capability_labels_instead_of_workflow_names():
    assert {need.value for need in MemoryNeed} == {
        "conversation_continuity",
        "topic_focus",
        "practice_generation",
        "grading_evidence",
        "planning_goal",
        "pending_interaction",
    }
    assert all(
        workflow_name not in {need.value for need in MemoryNeed}
        for workflow_name in {"explain", "validate", "grade", "plan"}
    )


def test_every_memory_need_maps_to_at_least_one_partition():
    assert set(MEMORY_NEED_PARTITIONS) == set(MemoryNeed)
    for partitions in MEMORY_NEED_PARTITIONS.values():
        assert partitions
        assert all(isinstance(partition, MemoryPartition) for partition in partitions)


def test_planning_goal_declares_learning_mastery_partition():
    assert (
        MemoryPartition.LEARNING_MASTERY
        in MEMORY_NEED_PARTITIONS[MemoryNeed.PLANNING_GOAL]
    )


def test_topic_focus_declares_learning_hypothesis_partition():
    assert (
        MemoryPartition.LEARNING_HYPOTHESIS
        in MEMORY_NEED_PARTITIONS[MemoryNeed.TOPIC_FOCUS]
    )
