"""
Loop action Schema（Pydantic model）
+
每轮 decision 必须结构化，包含 action 和 reasoning。
"""

from typing import Optional, Dict, Any, Literal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ActionType(str, Enum):
    """P0 允许的 Action 类型"""

    RETRIEVE_KNOWLEDGE = "retrieve_knowledge"
    FINISH = "finish"
    NEED_SCOPE = "need_scope"


class LoopAction(BaseModel):
    """Loop 动作"""

    action: ActionType = Field(..., description="要执行的动作")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="动作参数",
    )
    reasoning: str = Field(..., description="推理过程（为什么选这个动作）")


class LoopDecision(BaseModel):
    """Loop 决策输出"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "action": "retrieve_knowledge",
                "parameters": {"query": "进程调度算法", "limit": 5},
                "reasoning": "用户询问进程调度，需要先检索相关知识",
                "confidence": 0.95,
            }
        }
    )

    action: ActionType = Field(..., description="选定的动作")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="动作参数",
    )
    reasoning: str = Field(..., description="完整推理过程")
    confidence: float = Field(default=1.0, ge=0, le=1, description="置信度")


RouterAction = Literal[
    "direct_answer",
    "clarify",
    "explain",
    "validate",
    "grade",
    "plan",
]


TeachingMode = Literal[
    "answer_only",
    "explain",
    "explain_then_micro_check",
    "practice_weakness",
    "feedback",
    "plan",
    "clarify",
]


ReadToolIntent = Literal[
    "get_learning_snapshot",
    "get_weakness_findings",
    "retrieve_knowledge",
    "search_question_candidates",
]


class ConversationDecision(BaseModel):
    """ConversationTutorAgent 一次调用的业务分支与教学策略结果。

    ``action`` 只负责选择持久化的业务 workflow，``teaching_mode`` 负责描述
    该 workflow 应采用的教学方式。两者合并在同一个结构化输出中，避免在线
    Router 与 Tutor 对同一轮请求重复做一次 workflow 决策。

    ``reason_code`` 和 ``reason_codes`` 同时保留：前者是旧 Router 的兼容字段，
    后者是供审计、聚合和回放使用的稳定代码列表。模型不能通过这个结构直接
    写掌握度、薄弱点或任何学习事实。
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    action: RouterAction = Field(..., description="本轮下一步处理方式")
    confidence: float = Field(..., ge=0, le=1, description="路由置信度")
    reason_code: str = Field(..., min_length=1, max_length=64)
    reason_codes: list[str] = Field(
        default_factory=list,
        min_length=1,
        max_length=8,
        description="稳定的机器可读决策原因代码，首项与 reason_code 对齐",
    )
    teaching_mode: TeachingMode | None = Field(
        default=None,
        description="本轮业务分支采用的教学策略",
    )
    target_knowledge_point_ids: list[str] = Field(
        default_factory=list,
        max_length=32,
        description="本轮教学策略关注的知识点 ID，只读目标引用",
    )
    need_diagnostic_check: bool = Field(
        default=False,
        description="是否建议 Explain/Validate 交接一次受控诊断检查",
    )
    read_tool_intents: list[ReadToolIntent] = Field(
        default_factory=list,
        max_length=4,
        description="只读能力意图；实际执行仍由服务端 ToolRegistry 门禁",
    )
    public_summary: Optional[str] = Field(default=None, max_length=500)
    clarification_question: Optional[str] = Field(
        default=None,
        max_length=1000,
    )

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str) -> str:
        item = value.strip()
        if not item or not item.replace("_", "").isalnum() or not item[0].isalpha():
            raise ValueError("reason_code 必须使用稳定的 snake_case 代码")
        return item

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if not item:
                raise ValueError("reason_codes 不能包含空白代码")
            if not item.replace("_", "").isalnum() or not item[0].isalpha():
                raise ValueError("reason_codes 必须使用稳定的 snake_case 代码")
            if item not in normalized:
                normalized.append(item)
        return normalized

    @field_validator("target_knowledge_point_ids")
    @classmethod
    def validate_target_knowledge_point_ids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip()
            if not item:
                raise ValueError("target_knowledge_point_ids 不能包含空白 ID")
            if item not in normalized:
                normalized.append(item)
        return normalized

    @field_validator("read_tool_intents")
    @classmethod
    def validate_read_tool_intents(
        cls, values: list[ReadToolIntent]
    ) -> list[ReadToolIntent]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def align_reason_codes(self) -> "ConversationDecision":
        if self.reason_code not in self.reason_codes:
            self.reason_codes.insert(0, self.reason_code)
        return self


# 兼容现有 Router 调用方、测试和管理端审计命名。新代码优先使用
# ConversationDecision，旧代码仍可以安全导入 RouterDecision。
RouterDecision = ConversationDecision


class DirectAnswerOutput(BaseModel):
    """普通问答 Agent 的类型安全输出。"""

    content: str = Field(..., min_length=1, max_length=20000)
    public_summary: Optional[str] = Field(default=None, max_length=500)


class ExplanationOutput(BaseModel):
    """讲解产物输出"""

    outline: list = Field(default_factory=list, description="讲解提纲")
    body: str = Field(..., description="讲解正文（Markdown）")
    citations: list = Field(default_factory=list, description="引用列表")
    summary: str = Field(default="", description="一句话总结")


class GeneratedQuestionOption(BaseModel):
    key: str = Field(..., pattern=r"^[A-H]$")
    text: str = Field(..., min_length=1, max_length=1000)


class GeneratedPracticeQuestion(BaseModel):
    """题库无命中时由模型生成、且可被后续确定性批改的单选题。"""

    content: str = Field(..., min_length=1, max_length=5000)
    options: list[GeneratedQuestionOption] = Field(..., min_length=2, max_length=8)
    answer: str = Field(..., pattern=r"^[A-H]$")
    explanation: str = Field(..., min_length=1, max_length=5000)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    model_version: str | None = Field(default=None, max_length=64)
    answer_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="模型对自身标准答案的可信度，最终仍由服务端权重策略裁剪",
    )

    @model_validator(mode="after")
    def validate_answer(self):
        keys = [option.key for option in self.options]
        if len(keys) != len(set(keys)):
            raise ValueError("生成题选项 key 不能重复")
        if self.answer not in keys:
            raise ValueError("生成题答案必须属于选项")
        return self


class ArtifactContent(BaseModel):
    """Artifact 内容"""

    type: str = Field(..., description="产物类型")
    title: str = Field(..., description="标题")
    content: str = Field(..., description="内容（Markdown）")
    citations: list = Field(default_factory=list, description="引用")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")
