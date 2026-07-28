"""
Tool 注册表（name -> execute func）

P0 白名单只读工具：仅 retrieve_knowledge
"""

from typing import Callable, Any, Awaitable, Dict, Optional, List
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ToolSpec:
    """工具规格"""

    name: str
    description: str
    parameters: Dict[str, Any]
    execute: Callable
    read_only: bool = True  # P0 只允许只读工具
    allowed_workflows: tuple[str, ...] = ()
    injected_parameters: tuple[str, ...] = ()

    def audit_descriptor(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "read_only": self.read_only,
            "allowed_workflows": list(self.allowed_workflows),
        }


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        """注册工具"""
        self._tools[tool.name] = tool
        logger.info("工具注册", name=tool.name, read_only=tool.read_only)

    def get(self, name: str) -> Optional[ToolSpec]:
        """获取工具"""
        return self._tools.get(name)

    def list_tools(self) -> List[ToolSpec]:
        """列出所有工具"""
        return list(self._tools.values())

    def is_registered(self, name: str) -> bool:
        """检查工具是否已注册"""
        return name in self._tools

    def is_read_only(self, name: str) -> bool:
        """检查工具是否为只读"""
        tool = self._tools.get(name)
        return tool.read_only if tool else False

    def get_schemas(self) -> List[Dict[str, Any]]:
        """获取所有工具的Schema描述（用于Prompt）"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self._tools.values()
        ]

    async def execute(
        self,
        name: str,
        *,
        workflow: str,
        db: Any,
        arguments: Dict[str, Any],
        implementation: Callable[..., Awaitable[Any]] | None = None,
    ) -> Any:
        """校验注册、工作流白名单和参数形状后执行工具。"""
        tool = self.get(name)
        if tool is None:
            raise ValueError(f"未注册的 Agent tool: {name}")
        if workflow not in tool.allowed_workflows:
            raise PermissionError(f"workflow {workflow} 无权调用 Agent tool {name}")
        if not tool.read_only:
            raise PermissionError(f"Agent tool {name} 不是允许执行的只读工具")
        properties = set((tool.parameters.get("properties") or {}).keys()) | set(
            tool.injected_parameters
        )
        unknown = set(arguments) - properties
        if unknown:
            raise ValueError(f"Agent tool {name} 收到未知参数: {sorted(unknown)}")
        missing = set(tool.parameters.get("required") or []) - set(arguments)
        if missing:
            raise ValueError(f"Agent tool {name} 缺少必要参数: {sorted(missing)}")
        executor = implementation or tool.execute
        logger.info("执行已授权 Agent 工具", name=name, workflow=workflow)
        return await executor(db=db, **arguments)


# 全局实例
tool_registry = ToolRegistry()
