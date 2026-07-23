"""Agent 模型配置解析与 Pydantic AI 客户端生命周期。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

import openai
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.operations.settings_service import SystemSettingsService

logger = get_logger(__name__)


class AgentModelConfigurationError(RuntimeError):
    """Agent 没有可用模型配置。"""


@dataclass(frozen=True)
class AgentModelConfig:
    """一次 Agent 模型调用所需的不可变配置快照。"""

    source: str
    provider: str
    model_name: str
    api_key: str
    base_url: str
    temperature: float
    max_tokens: int
    timeout_seconds: int

    @property
    def model_settings(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


@dataclass(frozen=True)
class AgentModelSession:
    """已解析模型及本次调用的审计元数据。"""

    model: Model
    config: AgentModelConfig


async def load_agent_model_config(db: AsyncSession) -> AgentModelConfig:
    """优先读取管理员“问答 LLM”，未启用时再回退环境变量。"""
    runtime_settings = await SystemSettingsService(db).load()
    configured = runtime_settings.get("llm", {})
    config = configured if isinstance(configured, dict) else {}

    if config.get("enabled") is True:
        provider = str(config.get("provider") or "openai_compatible").strip()
        if provider != "openai_compatible":
            raise AgentModelConfigurationError(
                f"Agent 暂不支持模型服务类型 {provider!r}，请使用 OpenAI 兼容接口"
            )
        model_name = str(config.get("model") or "").strip()
        api_key = str(config.get("api_key") or settings.OPENAI_API_KEY or "").strip()
        if not model_name or not api_key:
            raise AgentModelConfigurationError(
                "管理员问答 LLM 已启用，但缺少模型名称或 API Key"
            )
        return AgentModelConfig(
            source="system_settings.llm",
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=str(config.get("base_url") or "").strip().rstrip("/"),
            temperature=float(config.get("temperature", 0.2)),
            max_tokens=int(config.get("max_tokens") or 2000),
            timeout_seconds=int(config.get("timeout_seconds") or 60),
        )

    api_key = str(settings.OPENAI_API_KEY or "").strip()
    model_name = str(settings.OPENAI_MODEL or "").strip()
    if api_key and model_name:
        return AgentModelConfig(
            source="environment",
            provider="openai_compatible",
            model_name=model_name,
            api_key=api_key,
            base_url="",
            temperature=0.2,
            max_tokens=2000,
            timeout_seconds=60,
        )

    raise AgentModelConfigurationError(
        "Agent 没有可用模型：请在管理员端启用“问答 LLM”，并配置模型名称与 API Key"
    )


@asynccontextmanager
async def open_agent_model(
    db: AsyncSession,
    *,
    run_id: str | None = None,
) -> AsyncIterator[AgentModelSession]:
    """创建独立 OpenAI 兼容客户端，并在模型调用结束后可靠关闭。"""
    config = await load_agent_model_config(db)
    options: dict[str, Any] = {
        "api_key": config.api_key,
        "timeout": config.timeout_seconds,
    }
    if config.base_url:
        options["base_url"] = config.base_url

    client = openai.AsyncOpenAI(**options)
    provider = OpenAIProvider(openai_client=client)
    model = OpenAIChatModel(config.model_name, provider=provider)
    if run_id:
        from app.modules.agent.models import AgentRun

        run = await db.get(AgentRun, run_id)
        if run:
            metadata = dict(run.metadata_json or {})
            metadata.update(
                {
                    "model_config_source": config.source,
                    "model_name": config.model_name,
                    "model_provider": config.provider,
                }
            )
            run.metadata_json = metadata
            await db.flush()
    logger.info(
        "Agent 模型配置解析完成",
        source=config.source,
        provider=config.provider,
        model=config.model_name,
        base_url=config.base_url or "(OpenAI 默认地址)",
    )
    try:
        yield AgentModelSession(model=model, config=config)
    finally:
        await client.close()
