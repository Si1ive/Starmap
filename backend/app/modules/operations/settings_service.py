"""
系统设置服务

当前用途：
1. 提供轻量级系统设置读写能力
2. 支持 MinerU PDF 解析服务的部署与运行配置

说明：
- 当前采用 MySQL `system_configs` 表持久化
- 后续可平滑迁移到独立配置中心
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.mysql_models import AuditLog, SystemConfig
from app.modules.corpus.document_parsers import inspect_parser_health

logger = get_logger(__name__)

# 四个"对话型/向量型"LLM 配置块的 key，供 admin 遍历做 api_key 脱敏与泛化端点路由。
LLM_CONFIG_KEYS = ("llm", "pdf_structure_llm", "outline_llm", "embedding", "doc_meta_llm", "enrich_llm")


class SystemSettingsService:
    """系统设置读写服务"""

    def __init__(self, db: Optional[AsyncSession]):
        self.db = db

    async def load(self) -> Dict[str, Any]:
        """读取系统设置并补齐默认值。"""
        if self.db is None:
            return self._default_settings()

        data: Dict[str, Any] = {}
        try:
            result = await self.db.execute(select(SystemConfig))
            rows = result.scalars().all()
            for row in rows:
                data[row.config_key] = row.config_value or {}
        except SQLAlchemyError as exc:
            logger.warning("系统设置读取失败，回退默认配置", error=str(exc))
            return self._default_settings()
        return self._merge_defaults(data)

    async def save(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """保存系统设置。"""
        db = self._require_db()
        merged = self._merge_defaults(data)
        for key, value in merged.items():
            result = await db.execute(
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
                db.add(row)
        await db.flush()
        return merged

    async def save_partial(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """按顶级 section 增量保存系统设置。"""
        current = await self.load()
        sanitized = self._sanitize_input(data)
        merged = self._merge_section_dicts(current, sanitized)
        return await self.save(merged)

    async def get_active_pdf_parser(self) -> str:
        """返回系统唯一支持的 PDF 解析器。"""
        return "mineru"

    async def get_pdf_parser_runtime_config(self) -> Dict[str, Any]:
        data = await self.load()
        parser_config = data.get("pdf_parser", {})
        defaults = self._default_settings()["pdf_parser"]
        merged = copy.deepcopy(defaults)
        merged.update(parser_config if isinstance(parser_config, dict) else {})
        merged["active_parser"] = "mineru"
        merged["service_mode"] = "mineru_only"
        return merged

    async def get_crawler_runtime_config(self) -> Dict[str, Any]:
        """Return the validated crawler settings used for the next task run."""
        data = await self.load()
        crawler_config = data.get("crawler", {})
        return self.normalize_crawler_settings(
            crawler_config if isinstance(crawler_config, dict) else {},
            reject_unknown=False,
        )

    async def update_crawler_settings(
        self,
        crawler_config: Dict[str, Any],
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate and persist crawler settings with an audit record."""
        current = await self.load()
        old_config = self.normalize_crawler_settings(
            current.get("crawler", {}),
            reject_unknown=False,
        )
        next_config = self.normalize_crawler_settings(crawler_config)
        current["crawler"] = next_config
        saved = await self.save(current)

        if next_config != old_config:
            audit = AuditLog(
                user_id=user_id,
                action="crawler_settings_update",
                resource_type="system_config",
                resource_id="crawler",
                old_values=self.redact_crawler_runtime_config(old_config),
                new_values=self.redact_crawler_runtime_config(next_config),
                ip_address=ip_address,
                user_agent=user_agent,
            )
            db = self._require_db()
            db.add(audit)
            await db.flush()

        return saved["crawler"]

    async def update_pdf_parser(
        self,
        parser_name: str,
        deployment_target: str = "local",
        local_service_endpoint: Optional[str] = None,
        remote_service_endpoint: Optional[str] = None,
        request_timeout_seconds: Optional[int] = None,
        processing_window_size: Optional[int] = None,
        switch_notes: str = "",
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """更新 MinerU 解析服务配置，并记录审计日志。"""
        normalized = str(parser_name).strip().lower()
        if normalized != "mineru":
            raise ValueError("PDF 解析器已固定为 mineru")
        target = str(deployment_target or "local").strip().lower()
        if target not in {"local", "remote"}:
            raise ValueError("pdf_parser.deployment_target 仅支持 local 或 remote")

        current = await self.load()
        current_parser_config = current.get("pdf_parser", {})
        old_parser = current_parser_config.get("active_parser", "")
        old_target = current_parser_config.get("deployment_target", "local")
        old_local_endpoint = current_parser_config.get(
            "local_service_endpoint",
            self._default_settings()["pdf_parser"]["local_service_endpoint"],
        )
        old_remote_endpoint = current_parser_config.get("remote_service_endpoint", "")
        old_timeout = int(
            current_parser_config.get(
                "request_timeout_seconds",
                self._default_settings()["pdf_parser"]["request_timeout_seconds"],
            )
        )
        old_processing_window_size = int(
            current_parser_config.get(
                "processing_window_size",
                self._default_settings()["pdf_parser"]["processing_window_size"],
            )
        )
        next_local_endpoint = (
            str(local_service_endpoint).strip()
            if local_service_endpoint is not None
            else str(old_local_endpoint or self._default_settings()["pdf_parser"]["local_service_endpoint"]).strip()
        )
        next_remote_endpoint = (
            str(remote_service_endpoint).strip()
            if remote_service_endpoint is not None
            else str(old_remote_endpoint or "").strip()
        )
        next_timeout = int(request_timeout_seconds or old_timeout or 600)
        if next_timeout < 5 or next_timeout > 600:
            raise ValueError("pdf_parser.request_timeout_seconds 仅支持 5-600 秒")
        next_processing_window_size = int(
            processing_window_size
            or current_parser_config.get(
                "processing_window_size",
                self._default_settings()["pdf_parser"]["processing_window_size"],
            )
            or self._default_settings()["pdf_parser"]["processing_window_size"]
        )
        if next_processing_window_size < 1 or next_processing_window_size > 64:
            raise ValueError("pdf_parser.processing_window_size 仅支持 1-64")

        is_switching = (
            normalized != old_parser
            or target != old_target
            or next_local_endpoint != str(old_local_endpoint or "")
            or next_remote_endpoint != str(old_remote_endpoint or "")
            or next_timeout != old_timeout
            or next_processing_window_size != old_processing_window_size
        )
        notes = (switch_notes or "").strip()

        if is_switching and not notes:
            raise ValueError("切换 PDF 解析器或部署位置必须填写切换备注，说明原因、部署步骤和回滚方案")

        if target == "remote":
            if not next_remote_endpoint:
                raise ValueError("远程解析服务模式必须填写 remote_service_endpoint")
            parsed = urlparse(next_remote_endpoint)
            if not (parsed.scheme and parsed.netloc):
                raise ValueError("remote_service_endpoint 地址格式不合法，需包含协议和主机")

        if is_switching and target == "local":
            parser_health = inspect_parser_health(
                normalized,
                {
                    "active_parser": normalized,
                    "deployment_target": target,
                    "local_service_endpoint": next_local_endpoint,
                    "remote_service_endpoint": next_remote_endpoint,
                    "request_timeout_seconds": next_timeout,
                    "processing_window_size": next_processing_window_size,
                },
            )
            if parser_health.get("health_status") != "ready":
                raise ValueError(
                    f"目标解析器 {normalized} 当前不可用：{parser_health.get('error_detail') or '未知错误'}。"
                    " 请先完成旧服务下线、新服务启动和依赖校验，再切换系统配置。"
                )

        current["pdf_parser"] = {
            "active_parser": "mineru",
            "service_mode": "mineru_only",
            "service_switch_notes": notes,
            "deployment_target": target,
            "local_service_endpoint": next_local_endpoint,
            "remote_service_endpoint": next_remote_endpoint,
            "request_timeout_seconds": next_timeout,
            "processing_window_size": next_processing_window_size,
        }
        saved = await self.save(current)

        if is_switching or notes:
            audit = AuditLog(
                user_id=user_id,
                action="pdf_parser_switch",
                resource_type="system_config",
                resource_id="pdf_parser",
                old_values={
                    "active_parser": old_parser,
                    "deployment_target": old_target,
                    "local_service_endpoint": old_local_endpoint,
                    "remote_service_endpoint": old_remote_endpoint,
                    "request_timeout_seconds": old_timeout,
                    "processing_window_size": old_processing_window_size,
                },
                new_values={
                    "active_parser": normalized,
                    "deployment_target": target,
                    "local_service_endpoint": next_local_endpoint,
                    "remote_service_endpoint": next_remote_endpoint,
                    "request_timeout_seconds": next_timeout,
                    "processing_window_size": next_processing_window_size,
                    "switch_notes": notes,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
            db = self._require_db()
            db.add(audit)
            await db.flush()

        return saved

    def _require_db(self) -> AsyncSession:
        if self.db is None:
            raise RuntimeError("数据库不可用，当前操作无法完成")
        return self.db

    @classmethod
    def normalize_crawler_settings(
        cls,
        data: Optional[Dict[str, Any]],
        *,
        reject_unknown: bool = True,
    ) -> Dict[str, Any]:
        """Validate the crawler settings that the Scrapy runtime can execute."""
        defaults = cls._default_settings()["crawler"]
        raw = dict(data or {})
        unknown = sorted(set(raw) - set(defaults))
        if reject_unknown and unknown:
            raise ValueError(f"不支持的配置项: {', '.join(unknown)}")

        values = copy.deepcopy(defaults)
        values.update({key: value for key, value in raw.items() if key in defaults})

        concurrent_requests = cls._bounded_int(
            values["concurrent_requests"],
            "crawler.concurrent_requests",
            1,
            64,
        )
        concurrent_per_domain = cls._bounded_int(
            values["concurrent_requests_per_domain"],
            "crawler.concurrent_requests_per_domain",
            1,
            64,
        )
        if concurrent_per_domain > concurrent_requests:
            raise ValueError(
                "crawler.concurrent_requests_per_domain 不能大于 concurrent_requests"
            )

        rotate_user_agent = cls._strict_bool(
            values["rotate_user_agent"],
            "crawler.rotate_user_agent",
        )
        user_agent = str(values["user_agent"] or "").strip()
        if not rotate_user_agent and not user_agent:
            raise ValueError("关闭随机 User-Agent 后必须填写 crawler.user_agent")
        if len(user_agent) > 512:
            raise ValueError("crawler.user_agent 最多支持 512 个字符")

        proxy_enabled = cls._strict_bool(
            values["proxy_enabled"],
            "crawler.proxy_enabled",
        )
        proxy_url = str(values["proxy_url"] or "").strip()
        if proxy_enabled and not proxy_url:
            raise ValueError("启用代理后必须填写 crawler.proxy_url")
        if proxy_url:
            parsed_proxy = urlparse(proxy_url)
            if parsed_proxy.scheme.lower() not in {"http", "https"}:
                raise ValueError("crawler.proxy_url 仅支持 http 或 https 代理")
            if not parsed_proxy.netloc:
                raise ValueError("crawler.proxy_url 地址格式不合法")

        log_level = str(values["log_level"] or "").strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError(
                "crawler.log_level 仅支持 DEBUG、INFO、WARNING 或 ERROR"
            )

        return {
            "concurrent_requests": concurrent_requests,
            "concurrent_requests_per_domain": concurrent_per_domain,
            "download_delay_seconds": cls._bounded_float(
                values["download_delay_seconds"],
                "crawler.download_delay_seconds",
                0,
                60,
            ),
            "request_timeout_seconds": cls._bounded_int(
                values["request_timeout_seconds"],
                "crawler.request_timeout_seconds",
                5,
                600,
            ),
            "retry_times": cls._bounded_int(
                values["retry_times"],
                "crawler.retry_times",
                0,
                10,
            ),
            "rotate_user_agent": rotate_user_agent,
            "user_agent": user_agent,
            "obey_robots_txt": cls._strict_bool(
                values["obey_robots_txt"],
                "crawler.obey_robots_txt",
            ),
            "follow_redirects": cls._strict_bool(
                values["follow_redirects"],
                "crawler.follow_redirects",
            ),
            "max_redirect_times": cls._bounded_int(
                values["max_redirect_times"],
                "crawler.max_redirect_times",
                0,
                50,
            ),
            "max_depth": cls._bounded_int(
                values["max_depth"],
                "crawler.max_depth",
                1,
                20,
            ),
            "proxy_enabled": proxy_enabled,
            "proxy_url": proxy_url,
            "log_level": log_level,
        }

    @staticmethod
    def redact_crawler_runtime_config(data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove proxy credentials before crawler settings enter audit logs."""
        redacted = copy.deepcopy(data)
        if redacted.get("proxy_url"):
            redacted["proxy_url"] = "[configured]"
        return redacted

    @staticmethod
    def _bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} 必须是整数")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"{field} 必须是整数")
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} 必须是整数") from exc
        if normalized < minimum or normalized > maximum:
            raise ValueError(f"{field} 仅支持 {minimum}-{maximum}")
        return normalized

    @staticmethod
    def _bounded_float(
        value: Any,
        field: str,
        minimum: float,
        maximum: float,
    ) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} 必须是数字")
        try:
            normalized = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} 必须是数字") from exc
        if not math.isfinite(normalized):
            raise ValueError(f"{field} 必须是有限数字")
        if normalized < minimum or normalized > maximum:
            raise ValueError(f"{field} 仅支持 {minimum}-{maximum}")
        return normalized

    @staticmethod
    def _strict_bool(value: Any, field: str) -> bool:
        if not isinstance(value, bool):
            raise ValueError(f"{field} 必须是布尔值")
        return value

    @classmethod
    def _merge_defaults(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        defaults = cls._default_settings()
        merged = copy.deepcopy(defaults)
        for key, value in data.items():
            if key not in merged:
                merged[key] = value
                continue
            if isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = cls._deep_merge_dicts(merged[key], value)
            else:
                merged[key] = value
        merged["pdf_parser"]["active_parser"] = "mineru"
        merged["pdf_parser"]["service_mode"] = "mineru_only"
        return merged

    @classmethod
    def _merge_section_dicts(cls, base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(base)
        for key, value in updates.items():
            if isinstance(merged.get(key), dict) and isinstance(value, dict):
                merged[key] = cls._deep_merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _deep_merge_dicts(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(base)
        for key, value in updates.items():
            if isinstance(merged.get(key), dict) and isinstance(value, dict):
                merged[key] = SystemSettingsService._deep_merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged

    @classmethod
    def _sanitize_input(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        defaults = cls._default_settings()
        sanitized: Dict[str, Any] = {}
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            if key == "pdf_parser":
                sanitized[key] = {
                    "active_parser": "mineru",
                    "service_mode": "mineru_only",
                    "service_switch_notes": value.get("service_switch_notes", ""),
                    "deployment_target": value.get(
                        "deployment_target",
                        defaults["pdf_parser"]["deployment_target"],
                    ),
                    "local_service_endpoint": value.get(
                        "local_service_endpoint",
                        defaults["pdf_parser"]["local_service_endpoint"],
                    ),
                    "remote_service_endpoint": value.get("remote_service_endpoint", ""),
                    "request_timeout_seconds": value.get(
                        "request_timeout_seconds",
                        defaults["pdf_parser"]["request_timeout_seconds"],
                    ),
                    "processing_window_size": value.get(
                        "processing_window_size",
                        defaults["pdf_parser"]["processing_window_size"],
                    ),
                }
                continue
            if key == "crawler":
                sanitized[key] = cls.normalize_crawler_settings(value)
                continue
            sanitized[key] = value
        return sanitized

    @staticmethod
    def _default_settings() -> Dict[str, Any]:
        return {
            "llm": {
                "enabled": False,
                "provider": "openai_compatible",
                "base_url": "",
                "api_key": "",
                "model": settings.OPENAI_MODEL,
                "temperature": 0.7,
                "max_tokens": 2000,
                "timeout_seconds": 60,
                "system_prompt": "你是一个专业的408考研学习助手，擅长解释知识点、题目分析与学习规划。",
            },
            "pdf_structure_llm": {
                "enabled": False,
                "provider": "openai_compatible",
                "base_url": "",
                "api_key": "",
                "model": settings.OPENAI_MODEL,
                "temperature": 0.1,
                "max_tokens": 2000,
                "timeout_seconds": 60,
                "system_prompt": "你是一个PDF题目结构分析专家，负责判断跨页、跨列导致的题目拆分和选项缺失问题。",
            },
            "outline_llm": {
                "enabled": False,
                "provider": "openai_compatible",
                "base_url": "",
                "api_key": "",
                "model": settings.OPENAI_MODEL,
                "temperature": 0.2,
                "max_tokens": 16000,
                "timeout_seconds": 180,
                "max_concurrency": 3,
                "system_prompt": (
                    "你是408考研大纲解析专家。负责把考试大纲文本拆分成结构化的章节树，"
                    "并区分『考察目标』（概括性的整门课要求）、『章节标题』（多层级）和『考点正文』。"
                ),
            },
            "embedding": {
                "enabled": False,
                "provider": "openai_compatible",
                "base_url": "",
                "api_key": "",
                "model": "text-embedding-ada-002",
                "dimension": 1536,
                "timeout_seconds": 60,
            },
            "doc_meta_llm": {
                "enabled": False,
                "provider": "openai_compatible",
                "base_url": "",
                "api_key": "",
                "model": settings.OPENAI_MODEL,
                "temperature": 0.1,
                "max_tokens": 1000,
                "timeout_seconds": 60,
                "system_prompt": (
                    "你是408考研资料元信息提取专家。从试卷/课本首页文本中识别"
                    "年份、是真题还是模拟题、来源/辅导机构、试卷名等信息，只输出 JSON。"
                ),
            },
            "enrich_llm": {
                "enabled": False,
                "provider": "openai_compatible",
                "base_url": "",
                "api_key": "",
                "model": settings.OPENAI_MODEL,
                "temperature": 0.3,
                "max_tokens": 2000,
                "timeout_seconds": 120,
                "system_prompt": (
                    "你是408考研内容富化专家。为题目生成参考答案与解析、标识所考知识点，"
                    "为知识点生成摘要/别名/要点。只输出 JSON，不要解释。"
                ),
            },
            "pdf_parser": {
                "active_parser": "mineru",
                "service_mode": "mineru_only",
                "service_switch_notes": "",
                "deployment_target": "local",
                "local_service_endpoint": settings.PDF_PARSER_LOCAL_ENDPOINT,
                "remote_service_endpoint": "",
                "request_timeout_seconds": 600,
                "processing_window_size": 1,
            },
            "crawler": {
                "concurrent_requests": 4,
                "concurrent_requests_per_domain": 2,
                "download_delay_seconds": 1.0,
                "request_timeout_seconds": 60,
                "retry_times": 3,
                "rotate_user_agent": True,
                "user_agent": "408StudyBot/1.0",
                "obey_robots_txt": False,
                "follow_redirects": True,
                "max_redirect_times": 20,
                "max_depth": 5,
                "proxy_enabled": False,
                "proxy_url": "",
                "log_level": "INFO",
            },
        }

    @staticmethod
    def _default_description(config_key: str) -> str:
        if config_key == "pdf_parser":
            return "MinerU 解析服务运行配置"
        if config_key == "llm":
            return "问答 LLM 配置"
        if config_key == "pdf_structure_llm":
            return "PDF 文档结构解析 LLM 配置"
        if config_key == "outline_llm":
            return "大纲拆分 LLM 配置"
        if config_key == "embedding":
            return "向量化 Embedding 配置"
        if config_key == "doc_meta_llm":
            return "文档元信息提取 LLM 配置"
        if config_key == "enrich_llm":
            return "语料富化增强 LLM 配置"
        if config_key == "crawler":
            return "Scrapy 爬虫运行配置"
        return "系统配置"
