"""Agent 执行异常到用户可见错误的稳定映射。"""

from dataclasses import dataclass

from .model_runtime.config import AgentModelConfigurationError


@dataclass(frozen=True)
class AgentPublicError:
    """可安全发送给用户的错误码与中文说明。"""

    code: str
    message: str


PUBLIC_ERROR_MESSAGES = {
    "agent_model_unavailable": (
        "Agent 模型尚未配置好，请联系管理员检查 Agent 模型配置。"
    ),
    "agent_response_too_long": (
        "回答内容超过了本轮允许的长度，生成已停止。已生成的内容会保留，"
        "你可以让 Agent 分段继续讲解。"
    ),
    "agent_context_too_long": (
        "当前对话内容超过了模型可处理的上下文长度。请新建会话或减少引用内容后重试。"
    ),
    "agent_model_parameter_invalid": (
        "当前模型的生成参数超出其支持范围，请联系管理员检查输出 Token 配置。"
    ),
    "agent_model_busy": "模型服务当前请求较多，请稍后重试。",
    "agent_model_timeout": "模型服务响应超时，请稍后重试。",
    "agent_response_format_invalid": (
        "模型返回内容格式不符合要求，系统未能完成解析。请重试；如果持续出现，请联系管理员。"
    ),
    "agent_run_failed": "这条回复生成失败，请稍后重试。",
}


def public_error_message(error_code: str | None) -> str:
    """根据持久化错误码恢复安全文案，兼容未知和历史错误码。"""

    return PUBLIC_ERROR_MESSAGES.get(
        error_code or "agent_run_failed",
        PUBLIC_ERROR_MESSAGES["agent_run_failed"],
    )


def classify_agent_error(
    error: str,
    *,
    exception: Exception | None = None,
) -> AgentPublicError:
    """按可操作原因分类内部异常，不向用户暴露供应商响应和堆栈。"""

    normalized = error.lower()

    if (
        isinstance(exception, AgentModelConfigurationError)
        or "missing credentials" in normalized
        or "agent 没有可用模型" in normalized
        or "管理员问答 llm" in normalized
        or "no available agent model" in normalized
    ):
        code = "agent_model_unavailable"
    elif "total_tokens_limit" in normalized or "usagelimitexceeded" in normalized:
        code = "agent_response_too_long"
    elif any(
        marker in normalized
        for marker in (
            "context_length_exceeded",
            "maximum context length",
            "context window",
            "input is too long",
            "prompt is too long",
        )
    ):
        code = "agent_context_too_long"
    elif (
        "max_completion_tokens" in normalized
        or ("max_tokens" in normalized and "invalid" in normalized)
        or "invalidparameter" in normalized
    ):
        code = "agent_model_parameter_invalid"
    elif "exceeded maximum output retries" in normalized:
        code = "agent_response_format_invalid"
    elif any(
        marker in normalized
        for marker in ("rate limit", "rate_limit", "status_code: 429", "http 429")
    ):
        code = "agent_model_busy"
    elif any(marker in normalized for marker in ("timeout", "timed out")):
        code = "agent_model_timeout"
    else:
        code = "agent_run_failed"

    return AgentPublicError(code=code, message=public_error_message(code))
