"""
单节点执行 + 状态转移
+
工作流引擎：按定义顺序执行节点，处理状态转移。
"""

import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, NodeResult, NodeStatus, ExecutionContext
from ..models import AgentStep
from ..events import event_store
from ..checkpoints import checkpoint_store
from ..time_utils import utc_now

logger = get_logger(__name__)


class WorkflowEngine:
    """工作流引擎"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def execute(
        self,
        workflow: WorkflowDefinition,
        context: ExecutionContext,
        run,
        *,
        resume_from: Optional[str] = None,
    ) -> NodeResult:
        """
        执行工作流

        从 entry_node 开始，按 edges 顺序执行，直到终止。
        """
        current_node_name = resume_from or workflow.entry_node
        visited = set()

        logger.info(
            "工作流开始执行",
            run_id=context.run_id,
            workflow=workflow.name,
            entry=current_node_name,
        )

        while current_node_name:
            if current_node_name in visited:
                logger.error("检测到循环依赖", node=current_node_name)
                return NodeResult.failure("工作流循环依赖")
            visited.add(current_node_name)

            node = workflow.nodes.get(current_node_name)
            if not node:
                logger.error("节点不存在", node=current_node_name)
                return NodeResult.failure(f"节点不存在: {current_node_name}")

            # 当前公开步骤必须落到 run 上，timeline snapshot 才能与实时
            # workflow.step.updated 事件保持一致，刷新后不会回退为空。
            run.current_public_step = node.name
            run.updated_at = utc_now()

            # 创建步骤记录
            step = AgentStep(
                id=f"step_{uuid.uuid4().hex[:20]}",
                run_id=context.run_id,
                node_name=node.name,
                node_type=node.node_type,
                status="running",
                started_at=utc_now(),
            )
            self.db.add(step)
            await self.db.flush()

            # 发布 step.started 事件
            await event_store.append(
                self.db,
                context.run_id,
                "step.started",
                {
                    "step_id": step.id,
                    "node_name": node.name,
                    "node_type": node.node_type,
                },
            )

            # 执行节点
            try:
                result = await node.execute(context, self.db)
                step.status = result.status.value
                step.output_data = result.output
                step.completed_at = utc_now()

                # 将节点输出写回 context，供后续节点消费
                if result.output:
                    for key, value in result.output.items():
                        context.set(key, value)

                # 同步模型调用计数到 run（预算可观测/可追溯）
                run.model_call_count = context.model_call_count

                # 发布事件
                if result.status == NodeStatus.COMPLETED:
                    await event_store.append(
                        self.db,
                        context.run_id,
                        "step.completed",
                        {
                            "step_id": step.id,
                            "node_name": node.name,
                            "output": result.output,
                        },
                    )
                elif result.status == NodeStatus.FAILED:
                    await event_store.append(
                        self.db,
                        context.run_id,
                        "step.failed",
                        {
                            "step_id": step.id,
                            "node_name": node.name,
                            "error": result.error,
                        },
                    )

                # 如果有产物，保存
                if result.artifact:
                    context.artifacts.append(result.artifact)

            except Exception as e:
                logger.error("节点执行异常", node=node.name, error=str(e))
                step.status = "failed"
                step.error_info = {"error": str(e)}
                step.completed_at = utc_now()

                await event_store.append(
                    self.db,
                    context.run_id,
                    "step.failed",
                    {"step_id": step.id, "node_name": node.name, "error": str(e)},
                )

                # 失败时尝试重试
                if node.max_retries > 0:
                    node.max_retries -= 1
                    logger.info("节点重试", node=node.name, remaining=node.max_retries)
                    visited.discard(current_node_name)
                    continue

                return NodeResult.failure(str(e))

            await self.db.flush()

            # 检查是否失败或等待
            if result.status == NodeStatus.FAILED:
                return result

            # 检查是否等待状态（如 wait_for_approval）
            if result.status == NodeStatus.WAITING:
                # 保存断点：记录当前节点和下一个节点
                await checkpoint_store.save(
                    self.db,
                    context.run_id,
                    {
                        "waiting_node": current_node_name,
                        "next_node": result.next_node,
                        "output": result.output,
                        "context_variables": context.variables,
                    },
                    f"ckp_{context.run_id}_wait",
                )
                logger.info(
                    "工作流进入等待状态", run_id=context.run_id, node=current_node_name
                )
                return result  # 返回 WAITING 状态，worker 会处理状态转移

            # 确定下一个节点
            if result.next_node:
                current_node_name = result.next_node
            else:
                next_nodes = workflow.get_next(current_node_name)
                if next_nodes and len(next_nodes) > 0:
                    current_node_name = next_nodes[0]
                else:
                    current_node_name = None

        logger.info("工作流执行完成", run_id=context.run_id, workflow=workflow.name)
        # 把最终产物挂到 NodeResult.artifact，供 worker 落库
        final_artifact = context.artifacts[-1] if context.artifacts else None
        return NodeResult(
            status=NodeStatus.COMPLETED,
            output={"artifacts": context.artifacts},
            artifact=final_artifact,
        )
