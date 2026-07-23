"""
Worker：租约获取 + 单节点执行循环
+
P0 简化版：单Worker执行，通过租约防止重复执行。
"""

import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.mysql import mysql_client
from .models import AgentRun, AgentRunOutbox, AgentEvent
from .state_machine import RunStatus, state_machine
from .events import event_store
from .outbox import outbox_store
from .service import AgentService
from .checkpoints import checkpoint_store
from .workflows.contracts import NodeStatus

logger = get_logger(__name__)

# Worker 唯一标识
WORKER_ID = f"worker_{uuid.uuid4().hex[:16]}"


class AgentWorker:
    """Agent 工作线程"""

    def __init__(self):
        self.running = False

    async def acquire_lease(self, db: AsyncSession, run: AgentRun, lease_duration: int = 300) -> bool:
        """
        获取Run的租约
        
        Args:
            run: AgentRun 实例
            lease_duration: 租约持续时间（秒）
            
        Returns:
            bool: 是否成功获取
        """
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=lease_duration)
        
        # 更新租约
        result = await db.execute(
            update(AgentRun)
            .where(AgentRun.id == run.id)
            .where(
                (AgentRun.lease_owner.is_(None)) |
                (AgentRun.lease_expires_at < now)
            )
            .values(
                lease_owner=WORKER_ID,
                lease_expires_at=expires_at,
            )
        )
        await db.flush()
        
        if result.rowcount > 0:
            logger.info("租约获取成功", run_id=run.id, worker=WORKER_ID)
            return True
        
        return False

    async def extend_lease(self, db: AsyncSession, run: AgentRun, lease_duration: int = 300) -> bool:
        """延长租约"""
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=lease_duration)
        
        result = await db.execute(
            update(AgentRun)
            .where(AgentRun.id == run.id)
            .where(AgentRun.lease_owner == WORKER_ID)
            .values(lease_expires_at=expires_at)
        )
        await db.flush()
        
        return result.rowcount > 0

    async def release_lease(self, db: AsyncSession, run: AgentRun) -> None:
        """释放租约"""
        await db.execute(
            update(AgentRun)
            .where(AgentRun.id == run.id)
            .values(lease_owner=None, lease_expires_at=None)
        )
        await db.flush()
        logger.info("租约释放", run_id=run.id, worker=WORKER_ID)

    async def process_run(self, db: AsyncSession, run: AgentRun) -> bool:
        """
        处理单个Run
        
        Args:
            run: AgentRun 实例
            
        Returns:
            bool: 是否成功处理
        """
        from .workflows.registry import workflow_registry
        from .workflows.engine import WorkflowEngine
        from .workflows.contracts import ExecutionContext

        # 获取租约
        if not await self.acquire_lease(db, run):
            logger.info("无法获取租约，跳过", run_id=run.id)
            return False

        try:
            # 状态转移：queued -> running
            if run.status == RunStatus.QUEUED.value:
                state_machine.transition(run, RunStatus.RUNNING)
                await event_store.append(db, run.id, "run.status_changed", {
                    "from": "queued",
                    "to": "running",
                })
                await db.flush()

            # 获取工作流
            workflow = workflow_registry.get(run.workflow_name)
            if not workflow:
                error_msg = f"工作流不存在: {run.workflow_name}"
                logger.error(error_msg, run_id=run.id)
                state_machine.transition(run, RunStatus.FAILED, reason=error_msg)
                run.error_message = error_msg
                await event_store.append(db, run.id, "run.failed", {
                    "run_id": run.id,
                    "error": error_msg,
                })
                await db.flush()
                return False

            # 延长租约
            await self.extend_lease(db, run)

            # 构建执行上下文（必须先创建，才能恢复断点变量）
            context = ExecutionContext(
                run_id=run.id,
                user_id=run.user_id,
                db=db,
            )

            # 尝试从断点恢复
            resume_from = None
            checkpoint = await checkpoint_store.load_latest(db, run.id)
            if checkpoint:
                # 恢复上下文变量（无论是否有 next_node 都要恢复）
                for key, value in checkpoint.get("context_variables", {}).items():
                    context.set(key, value)
                resume_from = checkpoint.get("next_node")
                if resume_from:
                    logger.info("从断点恢复", run_id=run.id, resume_from=resume_from)
                # 删除已使用的断点
                await checkpoint_store.delete_by_run(db, run.id)

            context.set("input_message", run.input_message)
            context.set("workflow", run.workflow_name)
            context.max_model_calls = run.max_model_calls
            context.model_call_count = run.model_call_count

            # 执行工作流
            engine = WorkflowEngine(db)
            result = await engine.execute(workflow, context, run, resume_from=resume_from)

            # 延长租约
            await self.extend_lease(db, run)

            # 处理结果
            if result.status == NodeStatus.COMPLETED:
                # 如果有产物，创建产物记录
                artifact = None
                if result.artifact:
                    service = AgentService(db)
                    artifact = await service.create_artifact(
                        run_id=run.id,
                        artifact_type=result.artifact.get("type", "message"),
                        content=result.artifact,
                    )
                    run.result_artifact_id = artifact.id
                    await event_store.append(db, run.id, "artifact.rendered", {
                        "run_id": run.id,
                        "artifact_id": artifact.id,
                        "artifact_type": artifact.artifact_type,
                    })

                display_result = None
                if result.artifact:
                    artifact_content = result.artifact.get("content")
                    if isinstance(artifact_content, str):
                        display_result = artifact_content
                        await event_store.append(db, run.id, "message.completed", {
                            "run_id": run.id,
                            "content": artifact_content,
                            "artifact_id": artifact.id if artifact else None,
                        })
                    else:
                        display_result = (
                            result.artifact.get("summary")
                            or result.artifact.get("title")
                        )

                state_machine.transition(run, RunStatus.COMPLETED)
                await event_store.append(db, run.id, "run.completed", {
                    "run_id": run.id,
                    "result": display_result,
                    "result_artifact_id": artifact.id if artifact else None,
                    "artifacts": result.output.get("artifacts", []) if result.output else [],
                })

            elif result.status == NodeStatus.WAITING:
                # 等待状态：转移到 waiting_for_approval
                state_machine.transition(run, RunStatus.WAITING_FOR_APPROVAL, reason="等待用户审批")
                run.error_message = None
                logger.info("Run 进入等待审批状态", run_id=run.id)
            else:
                error_msg = result.error or "工作流执行失败"
                state_machine.transition(run, RunStatus.FAILED, reason=error_msg)
                run.error_message = error_msg
                await event_store.append(db, run.id, "run.failed", {
                    "run_id": run.id,
                    "error": error_msg,
                })

            await db.flush()
            return True

        except Exception as e:
            logger.error("Run 处理异常", run_id=run.id, error=str(e))
            state_machine.transition(run, RunStatus.FAILED, reason=str(e))
            run.error_message = str(e)
            await event_store.append(db, run.id, "run.failed", {
                "run_id": run.id,
                "error": str(e),
            })
            await db.flush()
            return False

        finally:
            await self.release_lease(db, run)

    async def scan_and_process(self, limit: int = 10) -> int:
        """
        扫描outbox并处理待执行的Run
        
        Returns:
            int: 处理的数量
        """
        processed = 0

        # 先在独立事务里扫描出待处理的 outbox id 列表（read-only，提交后连接释放）
        async with mysql_client.session() as db:
            pending = await outbox_store.scan_pending(db, limit=limit)
            pending_ids = [(item.id, item.run_id) for item in pending]

        # 每个 run 用独立 session 处理，保证 process_run 内的写入随该事务提交落库
        for outbox_id, run_id in pending_ids:
            try:
                async with mysql_client.session() as db:
                    # 认领 outbox（原子更新，防止多 Worker 竞争）
                    if not await outbox_store.claim(db, outbox_id, WORKER_ID):
                        continue

                    result = await db.execute(
                        select(AgentRun).where(AgentRun.id == run_id)
                    )
                    run = result.scalar_one_or_none()

                    if not run:
                        logger.warning("Run 不存在", run_id=run_id)
                        await outbox_store.complete(db, outbox_id)
                        continue

                    success = await self.process_run(db, run)

                    if success:
                        await outbox_store.complete(db, outbox_id)
                    else:
                        await outbox_store.fail(db, outbox_id)

                processed += 1

            except Exception as e:
                logger.error("处理outbox异常", outbox_id=outbox_id, error=str(e))
                # 失败标记单独用一个 session，避免复用已回滚的事务
                try:
                    async with mysql_client.session() as db:
                        await outbox_store.fail(db, outbox_id)
                except Exception:
                    pass

        return processed

    async def start(self, interval: int = 5):
        """
        启动Worker循环
        
        Args:
            interval: 扫描间隔（秒）
        """
        self.running = True
        logger.info("Worker 启动", worker_id=WORKER_ID)
        
        while self.running:
            try:
                processed = await self.scan_and_process(limit=10)
                if processed > 0:
                    logger.info("Worker 处理完成", processed=processed, worker_id=WORKER_ID)
            except Exception as e:
                logger.error("Worker 扫描异常", error=str(e))
            
            await asyncio.sleep(interval)

    async def stop(self):
        """停止Worker"""
        self.running = False
        logger.info("Worker 停止", worker_id=WORKER_ID)


# 全局Worker实例（单例）
_worker_instance: Optional[AgentWorker] = None


async def start_worker(interval: int = 5):
    """启动Worker（后台任务）"""
    global _worker_instance
    _worker_instance = AgentWorker()
    # Run in a background task so it doesn't block startup
    asyncio.create_task(_worker_instance.start(interval))


async def stop_worker():
    """停止Worker"""
    global _worker_instance
    if _worker_instance:
        await _worker_instance.stop()
        _worker_instance = None


def get_worker() -> Optional[AgentWorker]:
    """获取Worker实例"""
    return _worker_instance
