"""
NodeResult、WorkflowDefinition 基类
+
P0 工作流合约定义。
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable, Awaitable
from enum import Enum


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
    def success(cls, output: Dict[str, Any] = None, next_node: Optional[str] = None) -> "NodeResult":
        return cls(status=NodeStatus.COMPLETED, output=output, next_node=next_node)

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
