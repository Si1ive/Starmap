from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.ai.embedding_service import EmbeddingService
from app.infrastructure.ai.llm_client import ChatLLMClient
from app.modules.chat.service import ChatService


@pytest.mark.asyncio
async def test_chat_llm_client_uses_async_openai_instance_api():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="LLM_OK"))]
    )
    sdk_client = MagicMock()
    sdk_client.chat.completions.create = AsyncMock(return_value=response)
    sdk_client.close = AsyncMock()
    client = ChatLLMClient(
        {
            "enabled": True,
            "api_key": "test-key",
            "base_url": "https://llm.example.com/v1/",
            "model": "test-model",
            "max_tokens": 128,
            "temperature": 0.1,
            "timeout_seconds": 12,
        }
    )
    messages = [{"role": "user", "content": "ping"}]

    with patch("openai.AsyncOpenAI", return_value=sdk_client) as constructor:
        response_obj, text = await client._chat(messages)

    assert response_obj is response
    assert text == "LLM_OK"
    constructor.assert_called_once_with(
        api_key="test-key",
        base_url="https://llm.example.com/v1",
        timeout=12,
    )
    sdk_client.chat.completions.create.assert_awaited_once_with(
        model="test-model",
        messages=messages,
        max_tokens=128,
        temperature=0.1,
    )
    sdk_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_llm_client_omits_token_limit_when_unlimited():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="LLM_OK"))]
    )
    sdk_client = MagicMock()
    sdk_client.chat.completions.create = AsyncMock(return_value=response)
    sdk_client.close = AsyncMock()
    client = ChatLLMClient(
        {
            "enabled": True,
            "api_key": "test-key",
            "model": "glm-5.2",
            "max_tokens": None,
            "temperature": 0.1,
        }
    )
    messages = [{"role": "user", "content": "ping"}]

    with patch("openai.AsyncOpenAI", return_value=sdk_client):
        await client._chat(messages)

    sdk_client.chat.completions.create.assert_awaited_once_with(
        model="glm-5.2",
        messages=messages,
        temperature=0.1,
    )
    sdk_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_embedding_service_uses_async_openai_instance_api():
    response = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.25, 0.75])]
    )
    sdk_client = MagicMock()
    sdk_client.embeddings.create = AsyncMock(return_value=response)
    sdk_client.close = AsyncMock()
    service = EmbeddingService(
        {
            "api_key": "embedding-key",
            "base_url": "https://embedding.example.com/v1/",
            "model": "embedding-model",
            "dimension": 2,
            "timeout_seconds": 8,
        }
    )

    with patch("openai.AsyncOpenAI", return_value=sdk_client) as constructor:
        response_obj = await service._create_embedding(["测试"])

    assert service._extract_embeddings(response_obj) == [[0.25, 0.75]]
    constructor.assert_called_once_with(
        api_key="embedding-key",
        base_url="https://embedding.example.com/v1",
        timeout=8,
    )
    sdk_client.embeddings.create.assert_awaited_once_with(
        input=["测试"],
        model="embedding-model",
    )
    sdk_client.close.assert_awaited_once()


def test_chat_service_environment_fallback_uses_shared_client():
    client = ChatService._environment_llm_client(
        max_tokens=321,
        temperature=0.4,
    )

    assert isinstance(client, ChatLLMClient)
    assert client.max_tokens == 321
    assert client.temperature == 0.4
    assert client.model
