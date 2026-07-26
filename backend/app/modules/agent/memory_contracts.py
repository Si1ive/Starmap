"""Stable memory partitions and capability labels for Agent memory."""

from __future__ import annotations

from enum import Enum


class MemoryPartition(str, Enum):
    """Authoritative partition names for persisted agent memory."""

    CURRENT_TURN_UNDERSTANDING = "current_turn_understanding"
    THREAD_TOPIC_STATE = "thread_topic_state"
    RECENT_CONVERSATION = "recent_conversation"
    TOPIC_SUMMARY = "topic_summary"
    LEARNING_MASTERY = "learning_mastery"
    ARTIFACT_AND_TASK = "artifact_and_task"
    PENDING_INTERACTION = "pending_interaction"
    USER_PREFERENCE = "user_preference"
    USER_GOAL = "user_goal"


class MemoryNeed(str, Enum):
    """Stable capability labels declared by workflows and selectors."""

    CONVERSATION_CONTINUITY = "conversation_continuity"
    TOPIC_FOCUS = "topic_focus"
    PRACTICE_GENERATION = "practice_generation"
    GRADING_EVIDENCE = "grading_evidence"
    PLANNING_GOAL = "planning_goal"
    PENDING_INTERACTION = "pending_interaction"


MEMORY_NEED_PARTITIONS: dict[MemoryNeed, tuple[MemoryPartition, ...]] = {
    MemoryNeed.CONVERSATION_CONTINUITY: (
        MemoryPartition.RECENT_CONVERSATION,
        MemoryPartition.TOPIC_SUMMARY,
        MemoryPartition.ARTIFACT_AND_TASK,
        MemoryPartition.PENDING_INTERACTION,
    ),
    MemoryNeed.TOPIC_FOCUS: (
        MemoryPartition.CURRENT_TURN_UNDERSTANDING,
        MemoryPartition.THREAD_TOPIC_STATE,
        MemoryPartition.TOPIC_SUMMARY,
    ),
    MemoryNeed.PRACTICE_GENERATION: (
        MemoryPartition.THREAD_TOPIC_STATE,
        MemoryPartition.LEARNING_MASTERY,
        MemoryPartition.ARTIFACT_AND_TASK,
    ),
    MemoryNeed.GRADING_EVIDENCE: (
        MemoryPartition.RECENT_CONVERSATION,
        MemoryPartition.ARTIFACT_AND_TASK,
        MemoryPartition.LEARNING_MASTERY,
    ),
    MemoryNeed.PLANNING_GOAL: (
        MemoryPartition.THREAD_TOPIC_STATE,
        MemoryPartition.USER_GOAL,
        MemoryPartition.USER_PREFERENCE,
        MemoryPartition.ARTIFACT_AND_TASK,
    ),
    MemoryNeed.PENDING_INTERACTION: (
        MemoryPartition.PENDING_INTERACTION,
        MemoryPartition.THREAD_TOPIC_STATE,
    ),
}
