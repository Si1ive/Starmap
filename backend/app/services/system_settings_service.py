"""
系统设置服务

当前用途：
1. 提供轻量级系统设置读写能力
2. 支持 PDF 解析器的单活切换配置

说明：
- 当前采用 MySQL `system_configs` 表持久化
- 后续可平滑迁移到独立配置中心
"""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mysql_models import SystemConfig

DEFAULT_SETTINGS: Dict[str, Any] = {
    "pdf_parser": {
        "active_parser": "docling",
        "service_mode": "single_active",
        "service_switch_notes": "",
    }
}


class SystemSettingsService:
    """系统设置读写服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def load(self) -> Dict[str, Any]:
        """读取系统设置并补齐默认值。"""
        data: Dict[str, Any] = {}
        result = await self.db.execute(select(SystemConfig))
        rows = result.scalars().all()
        for row in rows:
            data[row.config_key] = row.config_value or {}
        return self._merge_defaults(data)

    async def save(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """保存系统设置。"""
        merged = self._merge_defaults(data)
        for key, value in merged.items():
            result = await self.db.execute(
                select(SystemConfig).where(SystemConfig.config_key == key)
            )
            row = result.scalar_one_or_none()
            if row:
                row.config_value = value
            else:
                row = SystemConfig(
                    config_key=key,
                    config_value=value,
                    description=self._default_description(key),
                )
                self.db.add(row)
        await self.db.flush()
        return merged

    async def get_active_pdf_parser(self) -> str:
        """获取当前激活的 PDF 解析器。"""
        data = await self.load()
        parser_name = (
            data.get("pdf_parser", {}).get("active_parser") or DEFAULT_SETTINGS["pdf_parser"]["active_parser"]
        )
        normalized = str(parser_name).strip().lower()
        if normalized not in {"docling", "mineru"}:
            return DEFAULT_SETTINGS["pdf_parser"]["active_parser"]
        return normalized

    async def update_pdf_parser(self, parser_name: str, switch_notes: str = "") -> Dict[str, Any]:
        """更新当前激活的 PDF 解析器配置。"""
        normalized = str(parser_name).strip().lower()
        if normalized not in {"docling", "mineru"}:
            raise ValueError("pdf_parser.active_parser 仅支持 docling 或 mineru")

        current = await self.load()
        current["pdf_parser"] = {
            "active_parser": normalized,
            "service_mode": "single_active",
            "service_switch_notes": switch_notes or "",
        }
        return await self.save(current)

    @staticmethod
    def _merge_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
        merged = {
            "pdf_parser": {
                **DEFAULT_SETTINGS["pdf_parser"],
                **(data.get("pdf_parser") or {}),
            }
        }
        for key, value in data.items():
            if key != "pdf_parser":
                merged[key] = value
        return merged

    @staticmethod
    def _default_description(config_key: str) -> str:
        if config_key == "pdf_parser":
            return "PDF 解析器单活切换配置"
        return "系统配置"
