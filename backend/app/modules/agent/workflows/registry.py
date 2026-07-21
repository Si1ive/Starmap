"""
硬编码工作流注册（后续迁移到 DB）
+
P0 注册 conversation@v1 和 explain@v1。
"""

from typing import Dict, Optional
from dataclasses import dataclass

from .contracts import WorkflowDefinition


class WorkflowRegistry:
    """工作流注册表"""

    def __init__(self):
        self._workflows: Dict[str, WorkflowDefinition] = {}

    def register(self, workflow: WorkflowDefinition) -> None:
        key = f"{workflow.name}@{workflow.version}"
        self._workflows[key] = workflow

    def get(self, name: str, version: Optional[str] = None) -> Optional[WorkflowDefinition]:
        if version:
            key = f"{name}@{version}"
            return self._workflows.get(key)
        # 模糊匹配：返回最新版本
        candidates = [k for k in self._workflows if k.startswith(f"{name}@")]
        if candidates:
            return self._workflows[sorted(candidates)[-1]]
        return None

    def list(self) -> Dict[str, WorkflowDefinition]:
        return dict(self._workflows)


# 全局实例
workflow_registry = WorkflowRegistry()
