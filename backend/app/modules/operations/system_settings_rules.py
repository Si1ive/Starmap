"""系统设置默认值、合并与输入清洗规则。"""

from __future__ import annotations

import copy
from typing import Any, Dict

from app.core.config import settings
from app.modules.operations.crawler_settings import (
    default_crawler_settings,
    normalize_crawler_settings,
)


def default_system_settings() -> Dict[str, Any]:
    """返回一份可独立修改的完整系统默认配置。"""
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
            "system_prompt": "你是一个专业的408考研学习助手，擅长解释知识点、分析题目并根据对话提供练习反馈。",
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
        "crawler": default_crawler_settings(),
    }


def deep_merge_dicts(
    base: Dict[str, Any],
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """递归合并字典并保持输入对象不变。"""
    merged = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = deep_merge_dicts(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def merge_settings_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
    """将持久化设置补齐为完整运行配置。"""
    merged = deep_merge_dicts(default_system_settings(), data)
    merged["pdf_parser"]["active_parser"] = "mineru"
    merged["pdf_parser"]["service_mode"] = "mineru_only"
    return merged


def merge_section_dicts(
    base: Dict[str, Any],
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """按顶级配置分区合并增量更新。"""
    return deep_merge_dicts(base, updates)


def sanitize_settings_input(data: Dict[str, Any]) -> Dict[str, Any]:
    """过滤无效顶级输入并规范受约束的配置分区。"""
    defaults = default_system_settings()
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
            sanitized[key] = normalize_crawler_settings(value)
            continue
        sanitized[key] = copy.deepcopy(value)
    return sanitized


def default_config_description(config_key: str) -> str:
    """返回系统配置分区的持久化说明。"""
    descriptions = {
        "pdf_parser": "MinerU 解析服务运行配置",
        "llm": "问答 LLM 配置",
        "pdf_structure_llm": "PDF 文档结构解析 LLM 配置",
        "outline_llm": "大纲拆分 LLM 配置",
        "embedding": "向量化 Embedding 配置",
        "doc_meta_llm": "文档元信息提取 LLM 配置",
        "enrich_llm": "语料富化增强 LLM 配置",
        "crawler": "Scrapy 爬虫运行配置",
    }
    return descriptions.get(config_key, "系统配置")
