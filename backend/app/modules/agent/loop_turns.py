"""
Loop turn 持久化

每一轮 Agent Loop 的决策（action + reasoning）与 observation 全量落库，
支撑崩溃恢复与调试可追溯（路线图 P0 1.2）。
"""

import uuid
import json
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .models import AgentLoopTurn

logger = get_logger(__name__)


class LoopTurnStore:
    """Loop 决策存储"""

    async def record(
        self,
        session: AsyncSession,
        run_id: str,
        turn_no: int,
        decision: Dict[str, Any],
        action_key: Optional[str],
        observation: Optional[Dict[str, Any]] = None,
        parent_step_id: Optional[str] = None,
    ) -> AgentLoopTurn:
        """记录一轮 Loop 决策与 observation。"""
        turn = AgentLoopTurn(
            id=f"lt_{uuid.uuid4().hex[:20]}",
            run_id=run_id,
            parent_step_id=parent_step_id,
            turn_no=turn_no,
            decision_ref=json.dumps(decision, ensure_ascii=False),
            action_key=action_key,
            observation_ref=json.dumps(observation, ensure_ascii=False) if observation is not None else None,
        )
        session.add(turn)
        await session.flush()
        logger.debug("Loop turn 记录", run_id=run_id, turn_no=turn_no, action=action_key)
        return turn


# 全局实例
loop_turn_store = LoopTurnStore()
