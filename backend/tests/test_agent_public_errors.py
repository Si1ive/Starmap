"""Agent 用户可见错误分类测试。"""

import pytest

from app.modules.agent.public_errors import classify_agent_error


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            "Exceeded the total_tokens_limit of 4096 (total_tokens=4863)",
            "agent_response_too_long",
        ),
        (
            "maximum context length is 131072 tokens",
            "agent_context_too_long",
        ),
        (
            "InvalidParameter: Range of max_completion_tokens should be [1, 131072]",
            "agent_model_parameter_invalid",
        ),
        ("status_code: 429 rate limit exceeded", "agent_model_busy"),
        ("model request timed out", "agent_model_timeout"),
        (
            "Exceeded maximum output retries for structured result",
            "agent_response_format_invalid",
        ),
        ("unexpected provider failure", "agent_run_failed"),
    ],
)
def test_classify_agent_error_returns_stable_public_reason(error, expected_code):
    public_error = classify_agent_error(error)

    assert public_error.code == expected_code
    assert public_error.message
    assert error not in public_error.message


def test_response_format_error_only_explains_the_failure_reason():
    public_error = classify_agent_error("Exceeded maximum output retries (1)")

    assert public_error.code == "agent_response_format_invalid"
    assert public_error.message == "模型返回内容格式不符合要求，系统未能完成解析。"
