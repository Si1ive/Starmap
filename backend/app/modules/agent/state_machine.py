"""
Agent 基础状态机
+
核心状态转移：queued -> running -> completed / failed / waiting_for_user
"""

from enum import Enum
from typing import Optional, Callable, Dict, Any
from datetime import datetime

from app.core.logging import get_logger

logger = get_logger(__name__)


class RunStatus(str, Enum):
    """运行状态枚举"""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_FOR_USER = "waiting_for_user"
    WAITING_FOR_APPROVAL = "waiting_for_approval"


class TransitionError(Exception):
    """状态转移错误"""
    pass


# 合法状态转移图
VALID_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.FAILED},
    RunStatus.RUNNING: {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.WAITING_FOR_USER,
        RunStatus.WAITING_FOR_APPROVAL,
    },
    RunStatus.WAITING_FOR_USER: {RunStatus.RUNNING, RunStatus.FAILED},
    RunStatus.WAITING_FOR_APPROVAL: {RunStatus.RUNNING, RunStatus.FAILED},
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
}


class StateMachine:
    """Agent 状态机"""

    def __init__(self):
        self._transitions: Dict[str, list] = {}
        self._hooks: Dict[str, list] = {}

    def can_transition(self, from_status: RunStatus, to_status: RunStatus) -> bool:
        """检查状态转移是否合法"""
        return to_status in VALID_TRANSITIONS.get(from_status, set())

    def transition(self, run, to_status: RunStatus, *, reason: Optional[str] = None) -> bool:
        """
        执行状态转移
        
        Args:
            run: AgentRun 实例
            to_status: 目标状态
            reason: 转移原因
            
        Returns:
            bool: 是否成功转移
        """
        from_status = RunStatus(run.status)
        
        if not self.can_transition(from_status, to_status):
            raise TransitionError(
                f"非法状态转移: {from_status.value} -> {to_status.value}"
            )
        
        old_status = run.status
        run.status = to_status.value
        run.updated_at = datetime.utcnow()
        
        # 触发状态变化钩子
        self._trigger_hooks(run, old_status, to_status.value, reason)
        
        logger.info(
            "状态转移",
            run_id=run.id,
            from_status=old_status,
            to_status=to_status.value,
            reason=reason,
        )
        return True

    def _trigger_hooks(self, run, old_status: str, new_status: str, reason: Optional[str]):
        """触发状态变化钩子"""
        hook_key = f"{old_status}->{new_status}"
        for hook in self._hooks.get(hook_key, []):
            try:
                hook(run, old_status, new_status, reason)
            except Exception as e:
                logger.error("状态钩子执行失败", hook=hook.__name__, error=str(e))

    def add_hook(self, from_status: str, to_status: str, hook: Callable):
        """添加状态变化钩子"""
        hook_key = f"{from_status}->{to_status}"
        if hook_key not in self._hooks:
            self._hooks[hook_key] = []
        self._hooks[hook_key].append(hook)

    def is_terminal(self, status: RunStatus) -> bool:
        """判断是否为终止状态"""
        return status in {RunStatus.COMPLETED, RunStatus.FAILED}

    def is_active(self, status: RunStatus) -> bool:
        """判断是否为活跃状态（可被Worker处理）"""
        return status in {RunStatus.QUEUED, RunStatus.RUNNING}


# 全局状态机实例
state_machine = StateMachine()
