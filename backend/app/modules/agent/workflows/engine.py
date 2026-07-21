"""
单节点执行 + 状态转移
+
工作流引擎：按定义顺序执行节点，处理状态转移。
"""

from typing import Optional, Dict, Any
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, NodeResult, NodeStatus, ExecutionContext
from ..models import AgentStep
from ..state_machine import RunStatus, state_machine
from ..events import event_store

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
    ) -> NodeResult:
        """
        执行工作流
        
        从 entry_node 开始，按 edges 顺序执行，直到终止。
        """
        current_node_name = workflow.entry_node
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

            # 创建步骤记录
            step = AgentStep(
                run_id=context.run_id,
                node_name=node.name,
                node_type=node.node_type,
                status="running",
                started_at=datetime.utcnow(),
            )
            self.db.add(step)
            await self.db.flush()

            # 发布 step.started 事件
            await event_store.append(
                self.db, context.run_id, "step.started",
                {"step_id": step.id, "node_name": node.name, "node_type": node.node_type}
            )

            # 执行节点
            try:
                result = await node.execute(context, self.db)
                step.status = result.status.value
                step.output_data = result.output
                step.completed_at = datetime.utcnow()
                
                # 发布事件
                if result.status == NodeStatus.COMPLETED:
                    await event_store.append(
                        self.db, context.run_id, "step.completed",
                        {"step_id": step.id, "node_name": node.name, "output": result.output}
                    )
                elif result.status == NodeStatus.FAILED:
                    await event_store.append(
                        self.db, context.run_id, "step.failed",
                        {"step_id": step.id, "node_name": node.name, "error": result.error}
                    )

                # 如果有产物，保存
                if result.artifact:
                    context.artifacts.append(result.artifact)

            except Exception as e:
                logger.error("节点执行异常", node=node.name, error=str(e))
                step.status = "failed"
                step.error_info = {"error": str(e)}
                step.completed_at = datetime.utcnow()
                
                await event_store.append(
                    self.db, context.run_id, "step.failed",
                    {"step_id": step.id, "node_name": node.name, "error": str(e)}
                )
                
                # 失败时尝试重试
                if node.max_retries > 0:
                    node.max_retries -= 1
                    logger.info("节点重试", node=node.name, remaining=node.max_retries)
                    continue
                
                return NodeResult.failure(str(e))

            await self.db.flush()

            # 检查是否失败
            if result.status == NodeStatus.FAILED:
                return result

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
        return NodeResult.success({"artifacts": context.artifacts})
