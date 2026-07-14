from app.infrastructure.ai.llm_client import OutlineLLMClient


def test_outline_llm_client_uses_large_outline_defaults():
    client = OutlineLLMClient({})

    assert client.called_by == "outline_llm"
    assert client.temperature == 0.2
    assert client.max_tokens == 16000
    assert client.timeout_seconds == 180


def test_outline_llm_client_preserves_explicit_runtime_limits():
    client = OutlineLLMClient(
        {
            "temperature": 0.35,
            "max_tokens": 4096,
            "timeout_seconds": 90,
        }
    )

    assert client.temperature == 0.35
    assert client.max_tokens == 4096
    assert client.timeout_seconds == 90
