"""Agent 多模型配置的管理与查询服务。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.models import AgentModelConfigRecord

SECRET_KEEP_MASK = "__KEEP_EXISTING__"


class AgentModelConfigError(ValueError):
    """模型配置违反业务约束。"""


class AgentModelConfigNotFoundError(LookupError):
    """模型配置不存在。"""


class AgentModelConfigService:
    """维护多个 Agent 模型，并保证默认模型约束。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[AgentModelConfigRecord]:
        result = await self.db.execute(
            select(AgentModelConfigRecord).order_by(
                AgentModelConfigRecord.is_default.desc(),
                AgentModelConfigRecord.online.desc(),
                AgentModelConfigRecord.created_at.asc(),
            )
        )
        return list(result.scalars().all())

    async def get(self, model_config_id: str) -> AgentModelConfigRecord:
        record = await self.db.get(AgentModelConfigRecord, model_config_id)
        if record is None:
            raise AgentModelConfigNotFoundError(model_config_id)
        return record

    async def create(self, data: dict[str, Any]) -> AgentModelConfigRecord:
        display_name = self._required_text(data.get("display_name"), "模型显示名称")
        model_name = self._required_text(data.get("model_name"), "模型名称")
        await self._ensure_display_name_available(display_name)
        is_default = bool(data.get("is_default"))
        online = bool(data.get("online", False))
        selectable = bool(data.get("selectable", True))
        if is_default and not (online and selectable):
            raise AgentModelConfigError("默认模型必须同时处于上线且用户可选状态")

        record = AgentModelConfigRecord(
            id=uuid.uuid4().hex[:32],
            display_name=display_name,
            provider=data.get("provider", "openai_compatible"),
            base_url=data.get("base_url", "").strip().rstrip("/"),
            api_key=data.get("api_key", "").strip(),
            model_name=model_name,
            online=online,
            selectable=selectable,
            is_default=is_default,
            default_slot=1 if is_default else None,
            temperature=float(data.get("temperature", 0.2)),
            max_tokens=int(data.get("max_tokens", 2000)),
            timeout_seconds=int(data.get("timeout_seconds", 60)),
        )
        if record.provider != "openai_compatible":
            raise AgentModelConfigError("当前仅支持 OpenAI 兼容接口")
        if is_default:
            await self._clear_default()
        elif online and selectable and not await self.get_default():
            record.is_default = True
            record.default_slot = 1
        self.db.add(record)
        await self.db.flush()
        return record

    async def update(
        self,
        model_config_id: str,
        data: dict[str, Any],
    ) -> AgentModelConfigRecord:
        record = await self.get(model_config_id)
        if "display_name" in data:
            display_name = self._required_text(data["display_name"], "模型显示名称")
            await self._ensure_display_name_available(
                display_name, exclude_id=record.id
            )
            record.display_name = display_name
        if "provider" in data:
            if data["provider"] != "openai_compatible":
                raise AgentModelConfigError("当前仅支持 OpenAI 兼容接口")
            record.provider = data["provider"]
        if "base_url" in data:
            record.base_url = str(data["base_url"] or "").strip().rstrip("/")
        if "api_key" in data and data["api_key"] != SECRET_KEEP_MASK:
            record.api_key = str(data["api_key"] or "").strip()
        if "model_name" in data:
            record.model_name = self._required_text(data["model_name"], "模型名称")
        for field in ("temperature", "max_tokens", "timeout_seconds"):
            if field in data:
                setattr(record, field, data[field])

        next_online = bool(data.get("online", record.online))
        next_selectable = bool(data.get("selectable", record.selectable))
        next_default = bool(data.get("is_default", record.is_default))
        if record.is_default and not next_default:
            raise AgentModelConfigError(
                "请先将其他模型设为默认模型，再取消当前默认模型"
            )
        if record.is_default and not (next_online and next_selectable):
            raise AgentModelConfigError(
                "默认模型不能直接下线或设为不可选，请先切换默认模型"
            )
        if next_default and not (next_online and next_selectable):
            raise AgentModelConfigError("默认模型必须同时处于上线且用户可选状态")
        if next_default and not record.is_default:
            await self._clear_default()
        record.online = next_online
        record.selectable = next_selectable
        record.is_default = next_default
        record.default_slot = 1 if next_default else None
        if (
            not next_default
            and next_online
            and next_selectable
            and not await self.get_default()
        ):
            record.is_default = True
            record.default_slot = 1
        await self.db.flush()
        return record

    async def set_default(self, model_config_id: str) -> AgentModelConfigRecord:
        record = await self.get(model_config_id)
        if not (record.online and record.selectable):
            raise AgentModelConfigError("只有已上线且用户可选的模型才能设为默认模型")
        await self._clear_default()
        record.is_default = True
        record.default_slot = 1
        await self.db.flush()
        return record

    async def set_availability(
        self,
        model_config_id: str,
        *,
        online: bool,
        selectable: bool,
    ) -> AgentModelConfigRecord:
        return await self.update(
            model_config_id,
            {"online": online, "selectable": selectable},
        )

    async def get_default(self) -> AgentModelConfigRecord | None:
        result = await self.db.execute(
            select(AgentModelConfigRecord)
            .where(AgentModelConfigRecord.is_default.is_(True))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_public(self) -> list[AgentModelConfigRecord]:
        result = await self.db.execute(
            select(AgentModelConfigRecord)
            .where(
                AgentModelConfigRecord.online.is_(True),
                AgentModelConfigRecord.selectable.is_(True),
            )
            .order_by(
                AgentModelConfigRecord.is_default.desc(),
                AgentModelConfigRecord.display_name.asc(),
            )
        )
        return list(result.scalars().all())

    async def get_user_selectable(self, model_config_id: str) -> AgentModelConfigRecord:
        record = await self.get(model_config_id)
        if not (record.online and record.selectable):
            raise AgentModelConfigError("所选模型当前不可用，请重新选择")
        return record

    @staticmethod
    def to_admin_dict(record: AgentModelConfigRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "display_name": record.display_name,
            "provider": record.provider,
            "base_url": record.base_url,
            "api_key": SECRET_KEEP_MASK if record.api_key else "",
            "has_api_key": bool(record.api_key),
            "model_name": record.model_name,
            "online": record.online,
            "selectable": record.selectable,
            "is_default": record.is_default,
            "temperature": record.temperature,
            "max_tokens": record.max_tokens,
            "timeout_seconds": record.timeout_seconds,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    @staticmethod
    def to_runtime_dict(record: AgentModelConfigRecord) -> dict[str, Any]:
        return {
            "enabled": True,
            "provider": record.provider,
            "base_url": record.base_url,
            "api_key": record.api_key,
            "model": record.model_name,
            "temperature": record.temperature,
            "max_tokens": record.max_tokens,
            "timeout_seconds": record.timeout_seconds,
        }

    @staticmethod
    def to_public_dict(record: AgentModelConfigRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "display_name": record.display_name,
            "is_default": record.is_default,
        }

    async def _clear_default(self) -> None:
        await self.db.execute(
            update(AgentModelConfigRecord)
            .where(AgentModelConfigRecord.is_default.is_(True))
            .values(is_default=False, default_slot=None)
        )

    async def _ensure_display_name_available(
        self,
        display_name: str,
        *,
        exclude_id: str | None = None,
    ) -> None:
        query = select(AgentModelConfigRecord.id).where(
            AgentModelConfigRecord.display_name == display_name.strip()
        )
        if exclude_id:
            query = query.where(AgentModelConfigRecord.id != exclude_id)
        if await self.db.scalar(query):
            raise AgentModelConfigError("模型显示名称已存在")

    @staticmethod
    def _required_text(value: Any, label: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise AgentModelConfigError(f"{label}不能为空")
        return normalized
