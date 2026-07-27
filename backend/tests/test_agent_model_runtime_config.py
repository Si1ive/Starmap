"""Agent 运行时读取管理员问答 LLM 配置的测试。"""

from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

import pytest

from app.modules.agent.model_runtime.config import (
    AgentModelConfigurationError,
    load_agent_model_config,
    open_agent_model,
)
from app.modules.agent.model_configs import AgentModelConfigService
from app.modules.operations.settings_service import SystemSettingsService


@pytest.fixture(autouse=True)
def no_persisted_agent_default(monkeypatch):
    monkeypatch.setattr(
        AgentModelConfigService,
        "get_default",
        AsyncMock(return_value=None),
    )


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
    assert config.config_id is None
    assert config.model_name == "chat-model"
    assert config.base_url == "https://llm.example.com/v1"
    assert config.api_key == "admin-key"
    assert config.model_settings == {"temperature": 0.35, "max_tokens": 1234}


@pytest.mark.asyncio
async def test_agent_model_omits_output_limit_when_configured_as_unlimited(monkeypatch):
    record = SimpleNamespace(
        id="model_unlimited",
        display_name="无限输出模型",
        provider="openai_compatible",
        base_url="https://models.example.com/v1",
        api_key="model-key",
        model_name="glm-5.2",
        online=True,
        selectable=True,
        temperature=0.2,
        max_tokens=None,
        timeout_seconds=60,
    )
    monkeypatch.setattr(
        AgentModelConfigService,
        "get_default",
        AsyncMock(return_value=record),
    )

    config = await load_agent_model_config(MagicMock())

    assert config.max_tokens is None
    assert config.model_settings == {"temperature": 0.2}


@pytest.mark.asyncio
async def test_legacy_llm_null_output_limit_is_unlimited(monkeypatch):
    async def fake_load(self):
        return {
            "llm": {
                "enabled": True,
                "provider": "openai_compatible",
                "api_key": "admin-key",
                "model": "glm-5.2",
                "temperature": 0.3,
                "max_tokens": None,
                "timeout_seconds": 45,
            }
        }

    monkeypatch.setattr(SystemSettingsService, "load", fake_load)

    config = await load_agent_model_config(MagicMock())

    assert config.max_tokens is None
    assert config.model_settings == {"temperature": 0.3}


@pytest.mark.asyncio
async def test_agent_model_reports_clear_error_when_no_config(monkeypatch):
    async def fake_load(self):
        return {"llm": {"enabled": False}}

    monkeypatch.setattr(SystemSettingsService, "load", fake_load)
    monkeypatch.setattr(
        "app.modules.agent.model_runtime.config.settings.OPENAI_API_KEY", ""
    )

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
        assert session.invocation_id.startswith("model_call_")

    constructor.assert_called_once_with(
        api_key="admin-key",
        timeout=30,
        base_url="https://llm.example.com/v1",
    )
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_model_prefers_persisted_default_over_legacy_settings(monkeypatch):
    record = SimpleNamespace(
        id="model_default",
        display_name="默认模型",
        provider="openai_compatible",
        base_url="https://models.example.com/v1/",
        api_key="model-key",
        model_name="model-a",
        online=True,
        selectable=True,
        temperature=0.4,
        max_tokens=4096,
        timeout_seconds=50,
    )
    monkeypatch.setattr(
        AgentModelConfigService,
        "get_default",
        AsyncMock(return_value=record),
    )
    legacy_load = AsyncMock(side_effect=AssertionError("不应读取旧系统配置"))
    monkeypatch.setattr(SystemSettingsService, "load", legacy_load)

    config = await load_agent_model_config(MagicMock())

    assert config.source == "agent_model_configs"
    assert config.config_id == "model_default"
    assert config.model_name == "model-a"
    assert config.base_url == "https://models.example.com/v1"
    legacy_load.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_model_resolves_explicit_user_selection(monkeypatch):
    record = SimpleNamespace(
        id="model_selected",
        display_name="推理模型",
        provider="openai_compatible",
        base_url="",
        api_key="selected-key",
        model_name="model-b",
        online=True,
        selectable=True,
        temperature=0.1,
        max_tokens=8000,
        timeout_seconds=90,
    )
    get_user_selectable = AsyncMock(return_value=record)
    monkeypatch.setattr(
        AgentModelConfigService,
        "get_user_selectable",
        get_user_selectable,
    )

    config = await load_agent_model_config(
        MagicMock(),
        model_config_id="model_selected",
    )

    assert config.config_id == "model_selected"
    assert config.model_name == "model-b"
    get_user_selectable.assert_awaited_once_with("model_selected")
