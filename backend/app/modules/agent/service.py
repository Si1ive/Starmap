"""
AgentService（业务入口，编排 run 创建）
+
P0 核心业务逻辑入口。
"""

import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .models import (
    AgentApproval,
    AgentArtifact,
    AgentEvent,
    AgentInput,
    AgentRun,
    AgentThread,
)
from .state_machine import RunStatus, state_machine
from .events import event_store
from .outbox import outbox_store
from .thread_events import thread_event_store
from .time_utils import utc_now

logger = get_logger(__name__)


class AgentService:
    """Agent 业务服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== Thread 管理 ====================

    async def create_thread(
        self, user_id: str, title: Optional[str] = None
    ) -> AgentThread:
        """创建线程"""
        thread_id = f"thrd_{uuid.uuid4().hex[:20]}"
        thread = AgentThread(
            id=thread_id,
            user_id=user_id,
            title=title or "新会话",
            status="active",
        )
        self.db.add(thread)
        await self.db.flush()
        await self.db.refresh(thread)
        logger.info("线程创建", thread_id=thread_id, user_id=user_id)
        return thread

    async def get_thread(self, thread_id: str, user_id: str) -> Optional[AgentThread]:
        """获取线程（带权限校验）"""
        result = await self.db.execute(
            select(AgentThread)
            .where(AgentThread.id == thread_id)
            .where(AgentThread.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_threads(
        self, user_id: str, limit: int = 20, offset: int = 0
    ) -> List[AgentThread]:
        """列出用户的线程"""
        result = await self.db.execute(
            select(AgentThread)
            .where(AgentThread.user_id == user_id)
            .where(AgentThread.status == "active")
            .order_by(desc(AgentThread.updated_at))
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    # ==================== Run 管理 ====================

    async def create_run(
        self,
        user_id: str,
        thread_id: str,
        workflow_name: str,
        input_message: str,
        client_idempotency_key: Optional[str] = None,
        *,
        workflow_key: Optional[str] = None,
        workflow_version: Optional[str] = None,
        trigger_message_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        root_run_id: Optional[str] = None,
        presentation: str = "workflow",
        public_title: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
    ) -> AgentRun:
        """创建 Run"""
        # 幂等性检查
        if client_idempotency_key:
            existing = await self.db.execute(
                select(AgentRun).where(
                    AgentRun.user_id == user_id,
                    AgentRun.client_idempotency_key == client_idempotency_key,
                )
            )
            existing_run = existing.scalar_one_or_none()
            if existing_run:
                logger.info(
                    "幂等命中，返回已有Run", user_id=user_id, key=client_idempotency_key
                )
                return existing_run

        run_id = f"run_{uuid.uuid4().hex[:20]}"
        run = AgentRun(
            id=run_id,
            thread_id=thread_id,
            user_id=user_id,
            workflow_name=workflow_name,
            workflow_key=workflow_key or workflow_name.split("@", 1)[0],
            workflow_version=workflow_version,
            status=RunStatus.QUEUED.value,
            input_message=input_message,
            trigger_message_id=trigger_message_id,
            parent_run_id=parent_run_id,
            root_run_id=root_run_id,
            presentation=presentation,
            public_title=public_title,
            client_idempotency_key=client_idempotency_key,
            metadata_json=metadata_json,
        )
        self.db.add(run)
        await self.db.flush()
        if not run.root_run_id:
            run.root_run_id = run.id
            await self.db.flush()
        await self.db.refresh(run)

        # 记录事件
        await event_store.append(
            self.db,
            run_id,
            "run.created",
            {
                "run_id": run_id,
                "thread_id": thread_id,
                "workflow": workflow_name,
                "root_run_id": run.root_run_id,
                "parent_run_id": run.parent_run_id,
            },
        )

        # 投递到outbox
        await outbox_store.enqueue(self.db, run_id)

        logger.info("Run 创建", run_id=run_id, workflow=workflow_name)
        return run

    async def get_run(self, run_id: str, user_id: str) -> Optional[AgentRun]:
        """获取 Run（带权限校验）"""
        result = await self.db.execute(
            select(AgentRun)
            .where(AgentRun.id == run_id)
            .where(AgentRun.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_runs(
        self, thread_id: str, user_id: str, limit: int = 20
    ) -> List[AgentRun]:
        """列出线程的所有 Run"""
        result = await self.db.execute(
            select(AgentRun)
            .where(AgentRun.thread_id == thread_id)
            .where(AgentRun.user_id == user_id)
            .order_by(desc(AgentRun.created_at))
            .limit(limit)
        )
        return result.scalars().all()

    async def submit_input(
        self, run_id: str, user_id: str, input_text: str
    ) -> Optional[AgentRun]:
        """提交用户输入（用于 waiting_for_user 状态的 Run）"""
        run = await self.get_run(run_id, user_id)
        if not run:
            return None

        if run.status != RunStatus.WAITING_FOR_USER.value:
            logger.warning("Run 不在等待状态", run_id=run_id, status=run.status)
            return run

        # 状态转移
        state_machine.transition(run, RunStatus.RUNNING, reason="用户输入提交")

        # 更新输入消息
        run.input_message = input_text
        run.updated_at = utc_now()

        # 投递到outbox
        await outbox_store.enqueue(self.db, run_id)

        # 发送即时状态变更事件
        await event_store.append(
            self.db,
            run_id,
            "run.status_changed",
            {
                "from": "waiting_for_user",
                "to": "running",
                "reason": "用户输入提交",
            },
        )

        logger.info("用户输入提交", run_id=run_id, user_id=user_id)
        return run

    # ==================== Events ====================

    async def get_events(
        self,
        run_id: str,
        user_id: str,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> List[AgentEvent]:
        """获取事件（带权限校验）"""
        # 先校验run所有权
        run = await self.get_run(run_id, user_id)
        if not run:
            return []

        return await event_store.get_events(self.db, run_id, after_sequence, limit)

    # ==================== Artifacts ====================

    async def create_artifact(
        self,
        run_id: str,
        artifact_type: str,
        content: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentArtifact:
        """创建产物"""
        artifact_id = f"art_{uuid.uuid4().hex[:20]}"
        artifact = AgentArtifact(
            id=artifact_id,
            run_id=run_id,
            artifact_type=artifact_type,
            content_json=content,
            metadata_json=metadata,
        )
        self.db.add(artifact)
        await self.db.flush()
        await self.db.refresh(artifact)

        logger.info("产物创建", run_id=run_id, artifact_id=artifact_id)
        return artifact

    async def get_artifact(self, artifact_id: str) -> Optional[AgentArtifact]:
        """获取产物"""
        result = await self.db.execute(
            select(AgentArtifact).where(AgentArtifact.id == artifact_id)
        )
        return result.scalar_one_or_none()

    async def get_artifacts_by_run(self, run_id: str) -> List[AgentArtifact]:
        """获取Run的所有产物"""
        result = await self.db.execute(
            select(AgentArtifact)
            .where(AgentArtifact.run_id == run_id)
            .order_by(desc(AgentArtifact.created_at))
        )
        return result.scalars().all()

    # ==================== Input ====================

    async def create_input(
        self,
        run_id: str,
        input_key: str,
        prompt_ref: str,
        input_schema_version: str = "v1",
        expires_at: Optional[datetime] = None,
    ) -> "AgentInput":
        """创建待用户输入项"""
        input_id = f"inp_{uuid.uuid4().hex[:20]}"
        agent_input = AgentInput(
            id=input_id,
            run_id=run_id,
            input_key=input_key,
            input_schema_version=input_schema_version,
            prompt_ref=prompt_ref,
            status="pending",
            expires_at=expires_at,
        )
        self.db.add(agent_input)
        await self.db.flush()
        await self.db.refresh(agent_input)
        await thread_event_store.project_workflow_interaction(
            self.db,
            run_id,
            "workflow.input.required",
            status=RunStatus.WAITING_FOR_USER.value,
            payload={
                "input_id": agent_input.id,
                "input_key": agent_input.input_key,
            },
        )
        logger.info("输入项创建", run_id=run_id, input_id=input_id, key=input_key)
        return agent_input

    async def get_input(self, run_id: str, input_key: str) -> Optional["AgentInput"]:
        """获取输入项"""
        result = await self.db.execute(
            select(AgentInput)
            .where(AgentInput.run_id == run_id)
            .where(AgentInput.input_key == input_key)
        )
        return result.scalar_one_or_none()

    async def submit_input_answer(
        self,
        run_id: str,
        input_key: str,
        answer: str,
        user_id: str,
    ) -> Optional["AgentInput"]:
        """提交用户答案，恢复运行"""
        run = await self.get_run(run_id, user_id)
        if not run or run.status != RunStatus.WAITING_FOR_USER.value:
            return None
        agent_input = await self.get_input(run_id, input_key)
        if not agent_input:
            return None
        if agent_input.status != "pending":
            return None
        if agent_input.expires_at and agent_input.expires_at < utc_now():
            agent_input.status = "expired"
            await self.db.flush()
            return None
        agent_input.status = "answered"
        agent_input.answer_ref = answer
        agent_input.answered_by = user_id
        agent_input.updated_at = utc_now()
        await self.db.flush()
        # 恢复运行状态
        state_machine.transition(run, RunStatus.RUNNING, reason="用户输入已提交")
        await outbox_store.enqueue(self.db, run_id)
        await event_store.append(
            self.db,
            run_id,
            "run.status_changed",
            {
                "from": "waiting_for_user",
                "to": "running",
                "reason": "用户输入已提交",
            },
        )
        logger.info("用户答案提交", run_id=run_id, input_key=input_key, user_id=user_id)
        return agent_input

    # ==================== Approvals ====================

    async def create_approval(
        self,
        run_id: str,
        action_key: str,
        diff_ref: str,
        precondition_ref: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> "AgentApproval":
        """创建审批请求"""
        approval_id = f"aprv_{uuid.uuid4().hex[:20]}"
        approval = AgentApproval(
            id=approval_id,
            run_id=run_id,
            action_key=action_key,
            diff_ref=diff_ref,
            precondition_ref=precondition_ref,
            status="pending",
            expires_at=expires_at,
        )
        self.db.add(approval)
        await self.db.flush()
        await self.db.refresh(approval)
        await thread_event_store.project_workflow_interaction(
            self.db,
            run_id,
            "workflow.approval.required",
            status=RunStatus.WAITING_FOR_APPROVAL.value,
            payload={
                "approval_id": approval.id,
                "action_key": approval.action_key,
            },
        )
        logger.info(
            "审批请求创建", run_id=run_id, approval_id=approval_id, action=action_key
        )
        return approval

    async def get_approval(
        self, run_id: str, approval_id: str
    ) -> Optional["AgentApproval"]:
        """获取审批请求"""
        result = await self.db.execute(
            select(AgentApproval)
            .where(AgentApproval.id == approval_id)
            .where(AgentApproval.run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_run_approvals(self, run_id: str) -> list["AgentApproval"]:
        """获取Run的所有审批请求（按创建时间降序）"""
        result = await self.db.execute(
            select(AgentApproval)
            .where(AgentApproval.run_id == run_id)
            .order_by(desc(AgentApproval.created_at))
        )
        return result.scalars().all()

    async def decide_approval(
        self,
        run_id: str,
        approval_id: str,
        decision: str,
        decided_by: str,
    ) -> Optional["AgentApproval"]:
        """处理审批决定（approve/reject）"""
        run = await self.get_run(run_id, decided_by)
        if not run or run.status != RunStatus.WAITING_FOR_APPROVAL.value:
            return None
        approval = await self.get_approval(run_id, approval_id)
        if not approval:
            return None
        if approval.status != "pending":
            return None
        if approval.expires_at and approval.expires_at < utc_now():
            approval.status = "expired"
            await self.db.flush()
            return None
        approval.status = decision
        approval.decided_by = decided_by
        approval.updated_at = utc_now()
        await self.db.flush()
        # 恢复运行状态
        state_machine.transition(run, RunStatus.RUNNING, reason=f"审批已{decision}")
        await outbox_store.enqueue(self.db, run_id)
        # 发送即时状态变更事件
        await event_store.append(
            self.db,
            run_id,
            "run.status_changed",
            {
                "from": "waiting_for_approval",
                "to": "running",
                "reason": f"审批已{decision}",
            },
        )
        logger.info(
            "审批决定", run_id=run_id, approval_id=approval_id, decision=decision
        )
        return approval
