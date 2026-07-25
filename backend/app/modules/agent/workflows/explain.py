"""
explain@v1 节点和图
+
核心讲解工作流：
load_scope -> evidence_exploration_loop -> evidence_gate -> 
generate_explanation -> citation_gate -> render_artifact -> completed
"""

from typing import Dict, Any, Optional, List
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from .contracts import WorkflowDefinition, Node, NodeResult, ExecutionContext
from .registry import workflow_registry
from ..model_runtime.adapter import model_adapter
from ..model_runtime.schema import ExplanationOutput
from ..model_runtime.policy_gate import policy_gate

logger = get_logger(__name__)


async def _load_scope_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """读取用户授权的资料范围"""
    # P0 简化：从上下文获取学科范围（如果有）
    # 实际项目中应从用户配置读取
    scope = {
        "subjects": ["data_structure", "computer_organization", "os", "network"],
        "chapters": [],
        "mode": "all",
    }
    context.set("scope", scope)
    logger.info("加载用户范围", run_id=context.run_id, scope=scope)
    return NodeResult.success({"scope": scope}, next_node="evidence_loop")


async def _evidence_loop_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """证据探索循环（有界 Agent Loop）"""
    import json
    import re

    from ..tools.retrieve_knowledge import retrieve_knowledge
    from ..loop_turns import loop_turn_store
    from .contracts import ModelBudgetExceeded

    input_msg = context.get("input_message", "")
    scope = context.get("scope", {})

    # P0: 最多3轮决策
    max_turns = min(3, context.max_loop_turns)
    collected_evidence = []

    for turn in range(max_turns):
        # 构建决策prompt
        system_prompt = "你是一位考研408专家。请决定下一步动作。"
        user_prompt = f"""
用户问题：{input_msg}

目前已收集证据：{len(collected_evidence)}条

请在以下动作中选择：
1. retrieve_knowledge(query=...): 检索更多知识
2. finish(): 证据充分，结束循环
3. need_scope(): 需要用户补充资料范围

请用JSON格式返回：{{"action": "retrieve_knowledge", "parameters": {{"query": "..."}}, "reasoning": "..."}}
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # 预算校验：模型调用前扣减，超限则结束 Loop（用已收集证据降级）
        try:
            context.charge_model_call()
        except ModelBudgetExceeded as e:
            logger.warning("Loop 预算耗尽，提前结束", run_id=context.run_id, error=str(e))
            break

        try:
            response = await model_adapter.chat_completion(messages, temperature=0.2, max_tokens=500)

            try:
                data = json.loads(response)
            except json.JSONDecodeError:
                # 尝试从文本中提取JSON
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    await loop_turn_store.record(
                        db, context.run_id, turn,
                        decision={"raw": response[:1000]},
                        action_key=None,
                        observation={"error": "无法解析决策 JSON"},
                    )
                    break

            action = data.get("action", "")

            # 白名单校验
            if not policy_gate.validate(action):
                logger.warning("Action 未通过白名单", action=action)
                await loop_turn_store.record(
                    db, context.run_id, turn,
                    decision=data,
                    action_key=action,
                    observation={"error": "action 未通过白名单"},
                )
                break

            observation: Dict[str, Any] = {}
            if action == "retrieve_knowledge":
                params = data.get("parameters", {})
                result = await retrieve_knowledge(
                    db,
                    query=params.get("query", input_msg),
                    subject_id=params.get("subject_id"),
                    chapter_ids=params.get("chapter_ids"),
                    limit=params.get("limit", 5),
                    run_id=context.run_id,
                )
                observation = {"total": result.get("total", 0), "status": result.get("status")}
                collected_evidence.append({
                    "turn": turn,
                    "action": action,
                    "result": result,
                    "reasoning": data.get("reasoning", ""),
                })

            elif action == "finish":
                observation = {"decision": "finish"}
            elif action == "need_scope":
                # P0 简化：降级处理，继续用已有范围
                observation = {"decision": "need_scope", "handling": "降级继续"}
                logger.info("用户需要补充范围，降级处理", run_id=context.run_id)

            # 持久化本轮决策与 observation（#9）
            await loop_turn_store.record(
                db, context.run_id, turn,
                decision=data,
                action_key=action,
                observation=observation,
            )

            if action == "finish":
                break
            if action == "retrieve_knowledge" and len(collected_evidence) >= 2:
                # 证据足够，提前结束
                break

        except Exception as e:
            logger.error("Loop 执行异常", turn=turn, error=str(e))
            try:
                await loop_turn_store.record(
                    db, context.run_id, turn,
                    decision={"error": str(e)},
                    action_key=None,
                    observation={"error": str(e)},
                )
            except Exception:
                pass
            break

    context.set("evidence", collected_evidence)
    logger.info("证据收集完成", run_id=context.run_id, evidence_count=len(collected_evidence))
    return NodeResult.success({"evidence_count": len(collected_evidence)}, next_node="evidence_gate")


async def _evidence_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """证据校验"""
    evidence = context.get("evidence", [])
    
    # P0 简化：简单校验
    if len(evidence) == 0:
        logger.warning("证据不足", run_id=context.run_id)
        return NodeResult.success(
            {"gate_passed": False, "reason": "未检索到有效证据"},
            next_node="generate_explanation"  # 降级继续
        )
    
    logger.info("证据校验通过", run_id=context.run_id, count=len(evidence))
    return NodeResult.success(
        {"gate_passed": True, "evidence_count": len(evidence)},
        next_node="generate_explanation"
    )


async def _generate_explanation_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """生成结构化讲解"""
    input_msg = context.get("input_message", "")
    evidence = context.get("evidence", [])
    
    # 构建证据摘要
    evidence_summary = "\n\n".join([
        f"证据 {i+1}:\n" + str(e.get("result", {}).get("results", "")[:300])
        for i, e in enumerate(evidence)
    ]) if evidence else "无相关证据"
    
    prompt = f"""
请基于以下信息，为用户问题提供结构化的考研408知识点讲解。

用户问题：{input_msg}

检索到的证据：
{evidence_summary}

请以JSON格式返回：
{{
  "outline": ["要点1", "要点2", ...],
  "body": "详细讲解（Markdown格式）",
  "citations": ["引用来源1", "引用来源2"],
  "summary": "一句话总结"
}}
"""
    
    messages = [
        {"role": "system", "content": "你是考研408专家，请提供结构化的知识点讲解。"},
        {"role": "user", "content": prompt},
    ]

    from .contracts import ModelBudgetExceeded

    # 预算校验：讲解生成是核心产物，预算耗尽直接失败（不降级出空讲解）
    try:
        context.charge_model_call()
    except ModelBudgetExceeded as e:
        logger.warning("讲解生成预算耗尽", run_id=context.run_id, error=str(e))
        return NodeResult.failure(str(e))

    try:
        response = await model_adapter.chat_completion(messages, temperature=0.3, max_tokens=3000)
        
        import json
        import re
        # 提取JSON
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            data = {
                "outline": ["讲解生成失败"],
                "body": response,
                "citations": [],
                "summary": "",
            }
        
        context.set("explanation", data)
        logger.info("讲解生成完成", run_id=context.run_id)
        return NodeResult.success(data, next_node="citation_gate")
        
    except Exception as e:
        logger.error("讲解生成失败", run_id=context.run_id, error=str(e))
        return NodeResult.failure(str(e))


async def _citation_gate_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """引用校验"""
    explanation = context.get("explanation", {})
    citations = explanation.get("citations", [])
    
    # P0 简化：只要有引用或讲解正文不为空就通过
    body = explanation.get("body", "")
    if not body.strip():
        logger.warning("讲解正文为空", run_id=context.run_id)
        return NodeResult.failure("讲解正文为空")
    
    logger.info("引用校验通过", run_id=context.run_id, citation_count=len(citations))
    return NodeResult.success({"gate_passed": True}, next_node="render_artifact")


async def _render_artifact_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """渲染最终产物"""
    explanation = context.get("explanation", {})
    
    artifact = {
        "type": "explanation",
        "title": f"知识点讲解：{context.get('input_message', '未知话题')[:50]}",
        "content": explanation.get("body", ""),
        "citations": explanation.get("citations", []),
        "outline": explanation.get("outline", []),
        "summary": explanation.get("summary", ""),
    }
    
    logger.info("产物渲染完成", run_id=context.run_id)
    return NodeResult.success(
        {"artifact": artifact},
        next_node="completed",
        artifact=artifact,
    )


async def _completed_node(context: ExecutionContext, db: AsyncSession) -> NodeResult:
    """完成节点"""
    artifacts = context.get("artifacts", [])
    return NodeResult.success(
        {"completed": True, "artifacts": artifacts},
        artifact=artifacts[0] if artifacts else None,
    )


def build_explain_workflow() -> WorkflowDefinition:
    """构建 explain@v1 工作流"""
    wf = WorkflowDefinition(
        name="explain",
        version="v1",
        entry_node="load_scope",
        max_model_calls=6,
    )
    
    wf.add_node(Node(name="load_scope", node_type="action", execute=_load_scope_node, description="加载用户范围"))
    wf.add_node(Node(name="evidence_loop", node_type="loop", execute=_evidence_loop_node, description="证据探索"))
    wf.add_node(Node(name="evidence_gate", node_type="gate", execute=_evidence_gate_node, description="证据校验"))
    wf.add_node(Node(name="generate_explanation", node_type="action", execute=_generate_explanation_node, description="生成讲解"))
    wf.add_node(Node(name="citation_gate", node_type="gate", execute=_citation_gate_node, description="引用校验"))
    wf.add_node(Node(name="render_artifact", node_type="render", execute=_render_artifact_node, description="渲染产物"))
    wf.add_node(Node(name="completed", node_type="render", execute=_completed_node, description="完成"))
    
    wf.add_edge("load_scope", ["evidence_loop"])
    wf.add_edge("evidence_loop", ["evidence_gate"])
    wf.add_edge("evidence_gate", ["generate_explanation"])
    wf.add_edge("generate_explanation", ["citation_gate"])
    wf.add_edge("citation_gate", ["render_artifact"])
    wf.add_edge("render_artifact", ["completed"])
    
    return wf


# 注册
workflow_registry.register(build_explain_workflow())
