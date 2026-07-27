"""Agent 模型配置解析与 Pydantic AI 客户端生命周期。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
from typing import Any, AsyncGenerator, AsyncIterator
import uuid

import openai
from pydantic_ai.models import Model
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.agent.model_configs import (
    AgentModelConfigError,
    AgentModelConfigNotFoundError,
    AgentModelConfigService,
)
from app.modules.operations.settings_service import SystemSettingsService
from app.modules.monitoring.llm_calls import LLMCallRecorder
from pydantic_core import to_jsonable_python

logger = get_logger(__name__)


class AgentModelConfigurationError(RuntimeError):
    """Agent 没有可用模型配置。"""


@dataclass(frozen=True)
class AgentModelConfig:
    """一次 Agent 模型调用所需的不可变配置快照。"""

    source: str
    config_id: str | None
    provider: str
    model_name: str
    api_key: str
    base_url: str
    temperature: float
    max_tokens: int | None
    timeout_seconds: int

    @property
    def model_settings(self) -> dict[str, Any]:
        settings: dict[str, Any] = {"temperature": self.temperature}
        if self.max_tokens is not None:
            settings["max_tokens"] = self.max_tokens
        return settings


@dataclass(frozen=True)
class AgentModelSession:
    """已解析模型及本次调用的审计元数据。"""

    model: Model
    config: AgentModelConfig
    invocation_id: str


def _audit_model_messages(messages: list[ModelMessage]) -> list[dict[str, str]]:
    return [{
        "role": "pydantic_ai",
        "content": json.dumps(to_jsonable_python(messages), ensure_ascii=False),
    }]


def _audit_model_response(response: ModelResponse) -> tuple[str, dict[str, Any]]:
    text = "\n".join(
        part.content for part in response.parts if isinstance(part, TextPart)
    )
    return text, to_jsonable_python(response)


class AuditedOpenAIChatModel(OpenAIChatModel):
    """在 Pydantic AI 的每次真实 model request 边界写统一 LLM 审计。"""

    def __init__(self, *args, audit_run_id: str | None, audit_trace_id: str, audit_purpose: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._audit_run_id = audit_run_id
        self._audit_trace_id = audit_trace_id
        self._audit_purpose = audit_purpose

    def _recorder(self, messages: list[ModelMessage], settings: Any) -> LLMCallRecorder:
        return LLMCallRecorder(
            model=self.model_name,
            called_by="agent_runtime",
            purpose=self._audit_purpose,
            provider=self.system,
            base_url=self.base_url,
            request_messages=_audit_model_messages(messages),
            request_params=to_jsonable_python(settings or {}),
            trace_id=self._audit_trace_id,
            run_id=self._audit_run_id,
        )

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: Any,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        async with self._recorder(messages, model_settings) as recorder:
            response = await super().request(messages, model_settings, model_request_parameters)
            response_text, response_full = _audit_model_response(response)
            recorder.record_pydantic_response(
                response_text=response_text,
                usage=response.usage,
                response_full=response_full,
            )
            return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: Any,
        model_request_parameters: ModelRequestParameters,
        run_context: Any = None,
    ) -> AsyncGenerator[StreamedResponse]:
        async with self._recorder(messages, model_settings) as recorder:
            async with super().request_stream(
                messages,
                model_settings,
                model_request_parameters,
                run_context,
            ) as stream:
                try:
                    yield stream
                finally:
                    response = stream.get()
                    response_text, response_full = _audit_model_response(response)
                    recorder.record_pydantic_response(
                        response_text=response_text,
                        usage=response.usage,
                        response_full=response_full,
                    )


def _record_to_runtime_config(record: Any) -> AgentModelConfig:
    provider = str(record.provider or "openai_compatible").strip()
    if provider != "openai_compatible":
        raise AgentModelConfigurationError(
            f"Agent 暂不支持模型服务类型 {provider!r}，请使用 OpenAI 兼容接口"
        )
    model_name = str(record.model_name or "").strip()
    api_key = str(record.api_key or settings.OPENAI_API_KEY or "").strip()
    if not model_name or not api_key:
        raise AgentModelConfigurationError(
            f"Agent 模型 {record.display_name!r} 缺少模型名称或 API Key"
        )
    return AgentModelConfig(
        source="agent_model_configs",
        config_id=record.id,
        provider=provider,
        model_name=model_name,
        api_key=api_key,
        base_url=str(record.base_url or "").strip().rstrip("/"),
        temperature=float(record.temperature),
        max_tokens=(
            None if record.max_tokens is None else int(record.max_tokens)
        ),
        timeout_seconds=int(record.timeout_seconds),
    )


async def load_agent_model_config(
    db: AsyncSession,
    *,
    model_config_id: str | None = None,
) -> AgentModelConfig:
    """优先解析所选或默认多模型配置，再兼容旧系统配置与环境变量。"""
    model_service = AgentModelConfigService(db)
    if model_config_id:
        try:
            selected = await model_service.get_user_selectable(model_config_id)
        except (AgentModelConfigError, AgentModelConfigNotFoundError) as exc:
            raise AgentModelConfigurationError("所选 Agent 模型当前不可用") from exc
        return _record_to_runtime_config(selected)

    default_model = await model_service.get_default()
    if default_model is not None:
        if not (default_model.online and default_model.selectable):
            raise AgentModelConfigurationError(
                "默认 Agent 模型当前不可用，请联系管理员"
            )
        return _record_to_runtime_config(default_model)

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
        configured_max_tokens = (
            config["max_tokens"] if "max_tokens" in config else 2000
        )
        return AgentModelConfig(
            source="system_settings.llm",
            config_id=None,
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=str(config.get("base_url") or "").strip().rstrip("/"),
            temperature=float(config.get("temperature", 0.2)),
            max_tokens=(
                None
                if configured_max_tokens is None
                else int(configured_max_tokens)
            ),
            timeout_seconds=int(config.get("timeout_seconds") or 60),
        )

    api_key = str(settings.OPENAI_API_KEY or "").strip()
    model_name = str(settings.OPENAI_MODEL or "").strip()
    if api_key and model_name:
        return AgentModelConfig(
            source="environment",
            config_id=None,
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
    purpose: str = "Agent 模型调用",
) -> AsyncIterator[AgentModelSession]:
    """创建独立 OpenAI 兼容客户端，并在模型调用结束后可靠关闭。"""
    run = None
    requested_model_config_id = None
    if run_id:
        from app.modules.agent.models import AgentRun

        run = await db.get(AgentRun, run_id)
        if run:
            requested_model_config_id = (run.metadata_json or {}).get("model_config_id")

    config = await load_agent_model_config(
        db,
        model_config_id=requested_model_config_id,
    )
    options: dict[str, Any] = {
        "api_key": config.api_key,
        "timeout": config.timeout_seconds,
    }
    if config.base_url:
        options["base_url"] = config.base_url

    client = openai.AsyncOpenAI(**options)
    invocation_id = f"model_call_{uuid.uuid4().hex[:20]}"
    provider = OpenAIProvider(openai_client=client)
    model = AuditedOpenAIChatModel(
        config.model_name,
        provider=provider,
        audit_run_id=run_id,
        audit_trace_id=invocation_id,
        audit_purpose=purpose,
    )
    if run:
        metadata = dict(run.metadata_json or {})
        model_calls = list(metadata.get("model_calls") or [])
        model_calls.append(
            {
                "id": invocation_id,
                "model_config_id": config.config_id,
                "model_name": config.model_name,
                "provider": config.provider,
                "config_source": config.source,
                "purpose": purpose,
            }
        )
        metadata.update(
            {
                "model_config_id": config.config_id,
                "model_config_source": config.source,
                "model_name": config.model_name,
                "model_provider": config.provider,
                "model_calls": model_calls,
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
        yield AgentModelSession(
            model=model,
            config=config,
            invocation_id=invocation_id,
        )
    finally:
        await client.close()
