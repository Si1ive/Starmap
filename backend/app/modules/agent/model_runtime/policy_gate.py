"""
白名单校验（只允许 retrieve_knowledge）
+
P0 安全策略：严格限制 Loop 可用的工具。
"""

from typing import List, Set

from app.core.logging import get_logger
from .schema import ActionType

logger = get_logger(__name__)


class PolicyGate:
    """Loop Action 白名单校验"""

    # P0 白名单：只允许这些动作
    ALLOWED_ACTIONS: Set[str] = {
        "retrieve_knowledge",
        "finish",
        "need_scope",
    }

    # P0 严格禁止：写入操作
    FORBIDDEN_ACTIONS: Set[str] = {
        "create", "update", "delete", "insert",
        "modify", "write", "append",
    }

    def __init__(self):
        pass

    def validate(self, action: str) -> bool:
        """
        校验动作是否合法
        
        Args:
            action: 动作名称
            
        Returns:
            bool: 是否合法
        """
        # 白名单检查
        if action not in self.ALLOWED_ACTIONS:
            logger.warning("动作不在白名单中", action=action)
            return False

        # 禁止操作检查
        if action.lower() in self.FORBIDDEN_ACTIONS:
            logger.warning("检测到禁止操作", action=action)
            return False

        return True

    def get_allowed_actions(self) -> List[str]:
        """获取允许的动作列表"""
        return sorted(list(self.ALLOWED_ACTIONS))

    def format_allowed_actions_prompt(self) -> str:
        """格式化为 Prompt 可用的动作列表"""
        actions = self.get_allowed_actions()
        lines = ["可用的动作："]
        for a in actions:
            if a == "retrieve_knowledge":
                lines.append(f"  - {a}: 检索知识库（参数: query, subject_id, chapter_ids, limit）")
            elif a == "finish":
                lines.append(f"  - {a}: 证据充分，结束 Loop")
            elif a == "need_scope":
                lines.append(f"  - {a}: 需要用户补充资料范围")
        return "\n".join(lines)


# 全局实例
policy_gate = PolicyGate()
