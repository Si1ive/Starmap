"""Pydantic AI 类型安全路由运行时。"""

from dataclasses import dataclass
from typing import Sequence

from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model

from app.core.config import settings

from .schema import RouterAction, RouterDecision

ROUTER_ACTIONS: tuple[RouterAction, ...] = (
    "direct_answer",
    "clarify",
    "explain",
    "validate",
    "grade",
    "plan",
)


@dataclass(frozen=True)
class RouterDeps:
    """Router 本轮可见的可信运行元数据。"""

    thread_id: str
    user_id: str
    turn_id: str
    allowed_actions: tuple[RouterAction, ...] = ROUTER_ACTIONS
    token_budget: int = 4096


router_agent = Agent(
    deps_type=RouterDeps,
    output_type=RouterDecision,
    retries=1,
    instructions=(
        "你是 408 学习 Agent 的路由器，只判断本轮下一步处理方式，不直接回答用户。"
        "必须返回结构化 RouterDecision，不得输出隐藏推理过程。"
        "普通问答选择 direct_answer；缺少必要信息选择 clarify；"
        "需要形成业务执行链路时才选择 explain、validate、grade 或 plan。"
    ),
)


@router_agent.instructions
def _router_policy(context: RunContext[RouterDeps]) -> str:
    allowed = ", ".join(context.deps.allowed_actions)
    return (
        f"本轮允许的 action 仅为：{allowed}。"
        "reason_code 使用稳定、简短的机器可读标识。"
        "选择 clarify 时必须提供 clarification_question；"
        "其他 action 不得伪造用户授权或假定不存在的附件和上下文。"
    )


class RouterRuntime:
    """封装 Pydantic AI Agent，支持生产模型和测试模型替换。"""

    def __init__(self, model: Model | str | None = None):
        self.model = model or settings.AGENT_ROUTER_MODEL

    async def decide(
        self,
        current_input: str,
        *,
        deps: RouterDeps,
        message_history: Sequence[ModelMessage] = (),
    ) -> RouterDecision:
        result = await router_agent.run(
            current_input,
            deps=deps,
            message_history=message_history,
            model=self.model,
            usage_limits=UsageLimits(
                request_limit=2,
                total_tokens_limit=deps.token_budget,
            ),
        )
        decision = result.output
        if decision.action not in deps.allowed_actions:
            raise ValueError(f"Router 返回了未授权 action: {decision.action}")
        is_clarify = decision.action == "clarify"
        has_question = bool(decision.clarification_question)
        if is_clarify and not has_question:
            raise ValueError("clarify 路由必须提供 clarification_question")
        return decision


router_runtime = RouterRuntime()
