"""Agent 运行时读取管理员问答 LLM 配置的测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.agent.model_runtime.config import (
    AgentModelConfigurationError,
    load_agent_model_config,
    open_agent_model,
)
from app.modules.operations.settings_service import SystemSettingsService


@pytest.mark.asyncio
async def test_agent_model_prefers_enabled_admin_llm(monkeypatch):
    async def fake_load(self):
        return {
            "llm": {
                "enabled": True,
                "provider": "openai_compatible",
                "base_url": "https://llm.example.com/v1/",
                "api_key": "admin-key",
                "model": "chat-model",
                "temperature": 0.35,
                "max_tokens": 1234,
                "timeout_seconds": 45,
            }
        }

    monkeypatch.setattr(SystemSettingsService, "load", fake_load)
    config = await load_agent_model_config(MagicMock())

    assert config.source == "system_settings.llm"
    assert config.model_name == "chat-model"
    assert config.base_url == "https://llm.example.com/v1"
    assert config.api_key == "admin-key"
    assert config.model_settings == {"temperature": 0.35, "max_tokens": 1234}


@pytest.mark.asyncio
async def test_agent_model_reports_clear_error_when_no_config(monkeypatch):
    async def fake_load(self):
        return {"llm": {"enabled": False}}

    monkeypatch.setattr(SystemSettingsService, "load", fake_load)
    monkeypatch.setattr("app.modules.agent.model_runtime.config.settings.OPENAI_API_KEY", "")

    with pytest.raises(AgentModelConfigurationError, match="管理员端启用"):
        await load_agent_model_config(MagicMock())


@pytest.mark.asyncio
async def test_agent_model_uses_isolated_async_openai_client(monkeypatch):
    async def fake_load(self):
        return {
            "llm": {
                "enabled": True,
                "provider": "openai_compatible",
                "base_url": "https://llm.example.com/v1",
                "api_key": "admin-key",
                "model": "chat-model",
                "temperature": 0.2,
                "max_tokens": 2000,
                "timeout_seconds": 30,
            }
        }

    monkeypatch.setattr(SystemSettingsService, "load", fake_load)
    client = MagicMock()
    client.close = AsyncMock()
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(
        "app.modules.agent.model_runtime.config.openai.AsyncOpenAI",
        constructor,
    )

    async with open_agent_model(MagicMock()) as session:
        assert session.config.model_name == "chat-model"
        assert session.model.model_name == "chat-model"

    constructor.assert_called_once_with(
        api_key="admin-key",
        timeout=30,
        base_url="https://llm.example.com/v1",
    )
    client.close.assert_awaited_once()
