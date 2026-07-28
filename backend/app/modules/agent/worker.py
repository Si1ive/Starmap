"""
Worker：租约获取 + 单节点执行循环
+
P0 简化版：单Worker执行，通过租约防止重复执行。
"""

import uuid
import asyncio
from contextlib import suppress
from datetime import timedelta
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
from .conversation_summary import enqueue_conversation_summary_maintenance
from .memory_projection import project_completed_run_facts
from .memory_outbox import memory_outbox_consumer
from .preference_memory import enqueue_preference_candidate_extraction
from .workflows.contracts import NodeStatus
from .public_errors import classify_agent_error
from .time_utils import utc_now

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
        now = utc_now()
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
        now = utc_now()
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
            logger.info(
                "Run 开始处理",
                run_id=run.id,
                thread_id=run.thread_id,
                workflow=run.workflow_name,
                worker_id=WORKER_ID,
            )
            # 状态转移：queued -> running
            if run.status == RunStatus.QUEUED.value:
                state_machine.transition(run, RunStatus.RUNNING)
                await event_store.append(db, run.id, "run.status_changed", {
                    "from": "queued",
                    "to": "running",
                })
                # 运行态先提交，随后每个 WorkflowEngine 节点再提交自己的
                # 公开进度，SSE 才能在长任务执行期间持续读取。
                await db.commit()

            # 获取工作流
            workflow = workflow_registry.get(run.workflow_name)
            if not workflow:
                error_msg = f"工作流不存在: {run.workflow_name}"
                logger.error(error_msg, run_id=run.id)
                await self._record_failure(db, run, error_msg)
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
                    artifact_content = dict(result.artifact)
                    private_metadata = artifact_content.pop("_private_metadata", None)
                    artifact = await service.create_artifact(
                        run_id=run.id,
                        artifact_type=result.artifact.get("type", "message"),
                        content=artifact_content,
                        metadata=(
                            private_metadata
                            if isinstance(private_metadata, dict)
                            else None
                        ),
                    )
                    run.result_artifact_id = artifact.id
                    await event_store.append(db, run.id, "artifact.rendered", {
                        "run_id": run.id,
                        "artifact_id": artifact.id,
                        "artifact_type": artifact.artifact_type,
                    })
                    await project_completed_run_facts(db, run, artifact)

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
                await enqueue_conversation_summary_maintenance(db, run)
                await enqueue_preference_candidate_extraction(db, run)

            elif result.status == NodeStatus.WAITING:
                waiting_output = result.output or {}
                if waiting_output.get("waiting_for_user") is True:
                    waiting_status = RunStatus.WAITING_FOR_USER
                    waiting_reason = "等待用户补充信息"
                else:
                    # 兼容未显式声明等待类型的旧工作流：历史 WAITING 语义为等待审批。
                    waiting_status = RunStatus.WAITING_FOR_APPROVAL
                    waiting_reason = "等待用户审批"

                state_machine.transition(run, waiting_status, reason=waiting_reason)
                run.error_message = None
                await event_store.append(db, run.id, "run.status_changed", {
                    "from": RunStatus.RUNNING.value,
                    "to": waiting_status.value,
                    "reason": waiting_reason,
                })
                logger.info(
                    "Run 进入等待状态",
                    run_id=run.id,
                    status=waiting_status.value,
                )
            else:
                error_msg = result.error or "工作流执行失败"
                await self._record_failure(db, run, error_msg)

            await db.flush()
            return True

        except Exception as e:
            logger.error(
                "Run 处理异常",
                run_id=run.id,
                thread_id=run.thread_id,
                workflow=run.workflow_name,
                error=str(e),
                exc_info=True,
            )
            await self._record_failure(db, run, str(e), exception=e)
            await db.flush()
            return False

        finally:
            await self.release_lease(db, run)

    async def _record_failure(
        self,
        db: AsyncSession,
        run: AgentRun,
        error: str,
        *,
        exception: Exception | None = None,
    ) -> None:
        """持久化失败事实，并给静默 conversation run 创建用户可见失败消息。"""
        public_error = classify_agent_error(error, exception=exception)
        current_status = RunStatus(run.status)
        if current_status != RunStatus.FAILED:
            if not state_machine.can_transition(current_status, RunStatus.FAILED):
                logger.error(
                    "Run 已处于终态，无法再次记录失败状态",
                    run_id=run.id,
                    status=current_status.value,
                    error=error,
                )
                return
            state_machine.transition(run, RunStatus.FAILED, reason=error)
        run.error_message = error
        metadata = dict(run.metadata_json or {})
        metadata["error_code"] = public_error.code
        run.metadata_json = metadata
        await event_store.append(
            db,
            run.id,
            "run.failed",
            {
                "run_id": run.id,
                "error": error,
                "error_code": public_error.code,
                "public_message": public_error.message,
            },
        )

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
        if pending_ids:
            logger.info(
                "Worker 扫描到待执行任务",
                worker_id=WORKER_ID,
                count=len(pending_ids),
                run_ids=[run_id for _, run_id in pending_ids],
            )

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
                memory_processed = await memory_outbox_consumer.scan_and_process(limit=10)
                if processed > 0 or memory_processed > 0:
                    logger.info(
                        "Worker 处理完成",
                        processed=processed,
                        memory_processed=memory_processed,
                        worker_id=WORKER_ID,
                    )
            except Exception as e:
                logger.error("Worker 扫描异常", error=str(e))
            
            await asyncio.sleep(interval)

    async def stop(self):
        """停止Worker"""
        self.running = False
        logger.info("Worker 停止", worker_id=WORKER_ID)


# 全局Worker实例（单例）
_worker_instance: Optional[AgentWorker] = None
_worker_task: Optional[asyncio.Task] = None


async def start_worker(interval: int = 5):
    """启动Worker（后台任务）"""
    global _worker_instance, _worker_task
    if _worker_task and not _worker_task.done():
        logger.info("Agent Worker 已在运行", worker_id=WORKER_ID)
        return
    _worker_instance = AgentWorker()
    _worker_task = asyncio.create_task(
        _worker_instance.start(interval),
        name="agent-worker",
    )

    def _report_worker_exit(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error:
            logger.critical(
                "Agent Worker 后台任务异常退出",
                error=str(error),
                exc_info=(type(error), error, error.__traceback__),
            )
        else:
            logger.info("Agent Worker 后台任务已退出", worker_id=WORKER_ID)

    _worker_task.add_done_callback(_report_worker_exit)


async def stop_worker():
    """停止Worker"""
    global _worker_instance, _worker_task
    if _worker_instance:
        await _worker_instance.stop()
    if _worker_task:
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(_worker_task, timeout=10)
        if not _worker_task.done():
            _worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await _worker_task
    _worker_instance = None
    _worker_task = None


def get_worker() -> Optional[AgentWorker]:
    """获取Worker实例"""
    return _worker_instance
