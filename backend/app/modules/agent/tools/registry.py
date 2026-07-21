"""
Tool 注册表（name -> execute func）
+
P0 白名单只读工具：仅 retrieve_knowledge
"""

from typing import Callable, Any, Dict, Optional, List
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


# 全局实例
tool_registry = ToolRegistry()
