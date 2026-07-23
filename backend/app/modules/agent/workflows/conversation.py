"""
conversation@v1 节点和图
+
最小路由工作流：意图识别 -> 歧义判断 -> 路由调度。
"""

from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, Node, NodeResult, ExecutionContext
from .registry import workflow_registry
from ..model_runtime.adapter import model_adapter
from ..model_runtime.schema import LoopDecision

logger = get_logger(__name__)


async def _intent_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """意图识别节点"""
    input_msg = context.get("input_message", "")
    
    # P0: 轻量级规则+模型分类
    # 先检查是否包含明显的学习意图关键词
    study_keywords = ["什么是", "为什么", "怎么", "如何", "区别", "概念", "原理",
                      "算法", "数据结构", "操作系统", "计算机网络", "计算机组成"]
    
    is_study = any(kw in input_msg for kw in study_keywords)
    
    if is_study:
        logger.info("意图识别：学习查询", run_id=context.run_id)
        return NodeResult.success(
            {"intent": "explain", "confidence": 0.9},
            next_node="route"
        )
    
    # 用模型做意图分类（P0 简化版）
    try:
        messages = [
            {"role": "system", "content": "你是一个考研学习平台的意图识别助手。请判断用户的意图类型。"},
            {"role": "user", "content": f"用户消息：{input_msg}\n\n请判断意图类型，只返回以下之一：explain（知识讲解）、clarify（需要澄清）、other（其他）。"}
        ]
        response = await model_adapter.chat_completion(messages, temperature=0.1, max_tokens=50)
        
        intent = "explain" if "explain" in response.lower() else "clarify"
        confidence = 0.8 if intent == "explain" else 0.5
        
        logger.info("意图识别：模型分类", run_id=context.run_id, intent=intent)
        return NodeResult.success(
            {"intent": intent, "confidence": confidence},
            next_node="route"
        )
    except Exception as e:
        logger.warning("意图识别失败，降级为 explain", run_id=context.run_id, error=str(e))
        return NodeResult.success(
            {"intent": "explain", "confidence": 0.5, "fallback": True},
            next_node="route"
        )


async def _route_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """路由调度节点：创建 explain 子 run 并调度执行（路线图 1.3.1）"""
    from sqlalchemy import select
    from ..models import AgentRun
    from ..service import AgentService

    # engine 已将 intent 节点的 output 写回 context，直接读 intent
    intent = context.get("intent", "explain")
    reason = {
        "explain": "学习查询",
        "clarify": "需要澄清，降级处理",
    }.get(intent, "默认路由")

    # 目标 workflow：P0 只有 explain，clarify/其他都降级到 explain
    target_workflow = "explain"

    # 需要 thread_id 才能创建子 run —— 从当前 conversation run 读取
    result = await db.execute(
        select(AgentRun).where(AgentRun.id == context.run_id)
    )
    parent_run = result.scalar_one_or_none()
    if not parent_run:
        logger.error("conversation run 不存在，无法调度", run_id=context.run_id)
        return NodeResult.failure("父 run 不存在，无法调度子工作流")

    service = AgentService(db)
    child_run = await service.create_run(
        user_id=parent_run.user_id,
        thread_id=parent_run.thread_id,
        workflow_name=target_workflow,
        input_message=parent_run.input_message or context.get("input_message", ""),
        workflow_key=target_workflow,
        workflow_version="v1",
        trigger_message_id=parent_run.trigger_message_id,
        parent_run_id=parent_run.id,
        root_run_id=parent_run.root_run_id or parent_run.id,
        presentation="compact",
        public_title="整理讲解",
    )

    logger.info(
        "已创建 explain 子 run 并调度",
        run_id=context.run_id,
        child_run_id=child_run.id,
        intent=intent,
    )
    return NodeResult.success(
        {
            "target_workflow": f"{target_workflow}@v1",
            "child_run_id": child_run.id,
            "reason": reason,
        },
        next_node="completed",
    )


async def _completed_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """完成节点"""
    target = context.get("target_workflow", "explain@v1")
    child_run_id = context.get("child_run_id")

    return NodeResult.success(
        {
            "workflow": "conversation@v1",
            "target_workflow": target,
            "child_run_id": child_run_id,
            "message": f"已识别意图，已调度 {target}",
        },
        artifact={
            "type": "message",
            "title": "意图识别完成",
            "content": "已识别您的学习需求，正在为您准备讲解...",
            "child_run_id": child_run_id,
        },
    )


def build_conversation_workflow() -> WorkflowDefinition:
    """构建 conversation@v1 工作流"""
    wf = WorkflowDefinition(
        name="conversation",
        version="v1",
        entry_node="intent",
        max_model_calls=2,
    )
    
    wf.add_node(Node(
        name="intent",
        node_type="router",
        execute=_intent_node,
        description="意图识别",
    ))
    wf.add_node(Node(
        name="route",
        node_type="router",
        execute=_route_node,
        description="路由调度",
    ))
    wf.add_node(Node(
        name="completed",
        node_type="render",
        execute=_completed_node,
        description="完成",
    ))
    
    wf.add_edge("intent", ["route"])
    wf.add_edge("route", ["completed"])
    
    return wf


# 注册
workflow_registry.register(build_conversation_workflow())
