"""
NodeResult、WorkflowDefinition 基类
+
P0 工作流合约定义。
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable, Awaitable
from enum import Enum


_AUDIT_STRING_LIMIT = 4000
_AUDIT_COLLECTION_LIMIT = 40


def _audit_value(value: Any, *, depth: int = 0) -> Any:
    """把节点上下文压缩成可安全落库的 JSON 审计值。

    ExecutionContext 中既有普通字典，也有 Pydantic 模型和带消息正文的
    AgentRunContext。步骤输入需要能在管理端复盘，但不能把任意 Python 对象
    或无限增长的历史直接写入事件表，因此在这里统一做递归、截断和类型收敛。
    """
    if depth > 5:
        return "[nested value truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= _AUDIT_STRING_LIMIT:
            return value
        return f"{value[:_AUDIT_STRING_LIMIT]}...[truncated, total {len(value)}]"

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _audit_value(model_dump(mode="json"), depth=depth + 1)
        except Exception:
            return f"<{type(value).__name__}>"

    if isinstance(value, dict):
        items = list(value.items())[:_AUDIT_COLLECTION_LIMIT]
        result = {
            str(key): _audit_value(item, depth=depth + 1)
            for key, item in items
        }
        if len(value) > _AUDIT_COLLECTION_LIMIT:
            result["_truncated_items"] = len(value) - _AUDIT_COLLECTION_LIMIT
        return result

    if isinstance(value, (list, tuple, set)):
        values = list(value)
        result = [_audit_value(item, depth=depth + 1) for item in values[:_AUDIT_COLLECTION_LIMIT]]
        if len(values) > _AUDIT_COLLECTION_LIMIT:
            result.append(f"[...{len(values) - _AUDIT_COLLECTION_LIMIT} items truncated]")
        return result

    return f"<{type(value).__name__}>"


class ModelBudgetExceeded(Exception):
    """模型调用预算耗尽"""
    pass


class NodeStatus(str, Enum):
    """节点状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING = "waiting"


@dataclass
class NodeResult:
    """节点执行结果"""
    status: NodeStatus
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    next_node: Optional[str] = None  # 若为None则按默认流程
    artifact: Optional[Dict[str, Any]] = None

    @classmethod
    def success(
        cls,
        output: Optional[Dict[str, Any]] = None,
        next_node: Optional[str] = None,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> "NodeResult":
        return cls(
            status=NodeStatus.COMPLETED,
            output=output,
            next_node=next_node,
            artifact=artifact,
        )

    @classmethod
    def failure(cls, error: str, output: Optional[Dict[str, Any]] = None) -> "NodeResult":
        return cls(status=NodeStatus.FAILED, error=error, output=output)

    @classmethod
    def skip(cls, next_node: Optional[str] = None) -> "NodeResult":
        return cls(status=NodeStatus.SKIPPED, next_node=next_node)

    @classmethod
    def waiting(cls, next_node: Optional[str] = None, output: Optional[Dict[str, Any]] = None) -> "NodeResult":
        return cls(status=NodeStatus.WAITING, output=output, next_node=next_node)


@dataclass
class Node:
    """工作流节点"""
    name: str
    node_type: str  # router / action / gate / loop / render / wait
    execute: Callable[..., Awaitable[NodeResult]]
    description: str = ""
    max_retries: int = 0


@dataclass
class WorkflowDefinition:
    """工作流定义"""
    name: str
    version: str
    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: Dict[str, List[str]] = field(default_factory=dict)  # node -> [next_nodes]
    entry_node: str = ""
    max_model_calls: int = 6

    def add_node(self, node: Node) -> "WorkflowDefinition":
        self.nodes[node.name] = node
        return self

    def add_edge(self, from_node: str, to_nodes: List[str]) -> "WorkflowDefinition":
        self.edges[from_node] = to_nodes
        return self

    def get_next(self, node_name: str) -> Optional[List[str]]:
        return self.edges.get(node_name)


class ExecutionContext:
    """执行上下文"""
    def __init__(self, run_id: str, user_id: str, db: Any):
        self.run_id = run_id
        self.user_id = user_id
        self.db = db
        self.variables: Dict[str, Any] = {}
        self.model_call_count = 0
        self.max_model_calls = 6
        self.loop_turns = 0
        self.max_loop_turns = 3
        self.artifacts: List[Dict[str, Any]] = []

    def set(self, key: str, value: Any) -> None:
        self.variables[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.variables.get(key, default)

    def audit_input(self) -> Dict[str, Any]:
        """返回节点开始前可供管理员定位问题的上下文快照。"""
        return {
            "input_message": _audit_value(self.get("input_message")),
            "context_keys": sorted(self.variables),
            "variables": _audit_value(self.variables),
        }

    def charge_model_call(self, count: int = 1) -> None:
        """在调用模型前扣减预算，超限则抛 ModelBudgetExceeded。"""
        if self.model_call_count + count > self.max_model_calls:
            raise ModelBudgetExceeded(
                f"模型调用预算耗尽（已用 {self.model_call_count} / 上限 {self.max_model_calls}）"
            )
        self.model_call_count += count
