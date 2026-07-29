"""Agent 可用业务能力目录。

能力描述用于 Router 选择受控工作流；真正的数据写入仍由工作流和领域服务完成。
"""

from dataclasses import dataclass
from typing import Literal

from .model_runtime.schema import ReadToolIntent, RouterAction

CapabilityMode = Literal["response", "workflow", "interaction"]
SideEffect = Literal["none", "domain_write"]

READ_ONLY_CAPABILITY_POLICY_VERSION = "agent-read-capabilities-v1"
READ_ONLY_CAPABILITIES: tuple[dict[str, object], ...] = (
    {
        "name": "get_learning_snapshot",
        "description": "读取本轮已按用户、线程和版本冻结的学习状态摘要。",
        "read_only": True,
    },
    {
        "name": "get_weakness_findings",
        "description": "读取本轮快照中由评分事实派生的薄弱点和诊断建议。",
        "read_only": True,
    },
    {
        "name": "retrieve_knowledge",
        "description": "检索当前用户有权访问的知识资料或题目候选。",
        "read_only": True,
    },
    {
        "name": "search_question_candidates",
        "description": "按服务端冻结的知识点和题目范围读取题目候选。",
        "read_only": True,
    },
)


@dataclass(frozen=True)
class CapabilitySpec:
    key: str
    action: RouterAction
    title: str
    description: str
    mode: CapabilityMode
    side_effect: SideEffect = "none"
    tools: tuple[str, ...] = ()

    def model_descriptor(self) -> dict[str, object]:
        """只给模型公开完成路由所需的最小能力说明。"""
        return {
            "key": self.key,
            "action": self.action,
            "description": self.description,
        }

    def audit_descriptor(self) -> dict[str, object]:
        """给持久化审计和管理端公开策略信息，不含实现函数或密钥。"""
        return {
            **self.model_descriptor(),
            "title": self.title,
            "mode": self.mode,
            "side_effect": self.side_effect,
            "tools": list(self.tools),
        }


class CapabilityRegistry:
    policy_version = "agent-capabilities-v1"

    def __init__(self, specs: tuple[CapabilitySpec, ...]):
        self._by_action = {spec.action: spec for spec in specs}
        if len(self._by_action) != len(specs):
            raise ValueError("Agent capability action 必须唯一")

    def actions(self) -> tuple[RouterAction, ...]:
        return tuple(self._by_action)

    def require(self, action: RouterAction) -> CapabilitySpec:
        capability = self._by_action.get(action)
        if capability is None:
            raise ValueError(f"未注册的 Agent capability action: {action}")
        return capability

    def model_manifest(
        self,
        actions: tuple[RouterAction, ...] | None = None,
    ) -> tuple[dict[str, object], ...]:
        allowed = actions or self.actions()
        return tuple(self.require(action).model_descriptor() for action in allowed)

    def audit_manifest(
        self,
        actions: tuple[RouterAction, ...] | None = None,
    ) -> list[dict[str, object]]:
        allowed = actions or self.actions()
        return [self.require(action).audit_descriptor() for action in allowed]

    @staticmethod
    def read_only_model_manifest() -> tuple[dict[str, object], ...]:
        """返回 Tutor 可声明的只读能力，不包含执行函数或写入参数。"""
        return tuple(
            {
                "name": capability["name"],
                "description": capability["description"],
            }
            for capability in READ_ONLY_CAPABILITIES
        )

    @staticmethod
    def read_only_audit_manifest() -> list[dict[str, object]]:
        """返回只读能力的审计视图；实际调用仍由 ToolRegistry 再次门禁。"""
        return [
            {
                **capability,
                "policy_version": READ_ONLY_CAPABILITY_POLICY_VERSION,
            }
            for capability in READ_ONLY_CAPABILITIES
        ]

    @staticmethod
    def allowed_read_tool_intents() -> tuple[ReadToolIntent, ...]:
        return tuple(
            capability["name"]  # type: ignore[return-value]
            for capability in READ_ONLY_CAPABILITIES
        )


capability_registry = CapabilityRegistry(
    (
        CapabilitySpec(
            key="answer.direct",
            action="direct_answer",
            title="直接回答",
            description="回答问候、简短事实问题或当前讨论的普通追问。",
            mode="response",
        ),
        CapabilitySpec(
            key="interaction.clarify",
            action="clarify",
            title="请求补充信息",
            description="任务缺少必要对象或范围时，请用户补充最少信息。",
            mode="interaction",
        ),
        CapabilitySpec(
            key="learning.explain",
            action="explain",
            title="整理讲解",
            description="结合冻结对话上下文和授权资料检索，系统讲解知识点。",
            mode="workflow",
            tools=(
                "get_learning_snapshot",
                "get_weakness_findings",
                "retrieve_knowledge",
            ),
        ),
        CapabilitySpec(
            key="practice.prepare",
            action="validate",
            title="生成专项练习",
            description="检索或生成题目，并幂等创建可进入练习页的草稿。",
            mode="workflow",
            side_effect="domain_write",
            tools=(
                "get_learning_snapshot",
                "get_weakness_findings",
                "retrieve_knowledge",
                "search_question_candidates",
            ),
        ),
        CapabilitySpec(
            key="assessment.grade",
            action="grade",
            title="分析作答",
            description="基于冻结题目和可信答案确定性批改；成功后投影学习证据。",
            mode="workflow",
            side_effect="domain_write",
        ),
        CapabilitySpec(
            key="learning.plan",
            action="plan",
            title="调整学习计划",
            description="基于已确认目标和学习证据生成需要用户审批的学习计划。",
            mode="workflow",
            side_effect="domain_write",
        ),
    )
)
