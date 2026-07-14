"""考试大纲 LLM 客户端运行时配置。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.ai.llm_client import OutlineLLMClient
from app.modules.operations.settings_service import SystemSettingsService


async def load_outline_llm_client(db: AsyncSession) -> OutlineLLMClient:
    """按系统设置构建考试大纲专用 LLM 客户端。"""
    runtime_settings = await SystemSettingsService(db).load()
    config = runtime_settings.get("outline_llm", {})
    return OutlineLLMClient(config if isinstance(config, dict) else {})
