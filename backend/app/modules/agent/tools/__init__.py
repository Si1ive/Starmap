"""Agent Tools 包"""

from .registry import ToolRegistry, tool_registry
from .get_learning_snapshot import register_get_learning_snapshot
from .get_weakness_findings import register_get_weakness_findings
from .retrieve_knowledge import register_retrieve_knowledge
from .search_question_candidates import register_search_question_candidates

register_get_learning_snapshot(tool_registry)
register_get_weakness_findings(tool_registry)
register_retrieve_knowledge(tool_registry)
register_search_question_candidates(tool_registry)

__all__ = ["ToolRegistry", "tool_registry"]
