"""
共享 LLM 客户端

把 PDF 结构解析、大纲拆分、问答等多处重复的 OpenAI 兼容调用收敛到一处：
- BaseLLMClient：统一 config 解析、is_available 判断、chat/chat_messages 调用与日志记录
- PDFStructureLLMClient / OutlineLLMClient / ChatLLMClient：各自默认 system_prompt 与 called_by

注意：沿用老版 openai 全局变量（openai.api_key / api_base）的 save-restore 方案，
多配置并存时非线程安全，仅作缓解；彻底修复需迁移到 openai v1 client，另起任务。
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm_call_recorder import LLMCallRecorder

logger = get_logger(__name__)


def extract_json_block(text: str) -> Any:
    """从 LLM 返回里抠出 JSON（容忍 ```json 包裹 / 前后噪声）。"""
    if not text:
        raise ValueError("LLM 返回为空")
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    if not cleaned.startswith("{") and not cleaned.startswith("["):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


class BaseLLMClient:
    """OpenAI 兼容 LLM 客户端基类。"""

    # 子类覆盖：日志归因 + 默认提示词 + 默认温度
    called_by: str = "llm"
    default_system_prompt: str = "你是一个助手。"
    default_temperature: float = 0.2
    default_purpose: Optional[str] = None

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.enabled = bool(config.get("enabled"))
        self.provider = str(config.get("provider") or "openai_compatible")
        self.base_url = str(config.get("base_url") or "").strip()
        self.api_key = str(config.get("api_key") or settings.OPENAI_API_KEY or "").strip()
        self.model = str(config.get("model") or settings.OPENAI_MODEL).strip()
        self.temperature = float(config.get("temperature", self.default_temperature))
        self.max_tokens = int(config.get("max_tokens", 2000))
        self.timeout_seconds = int(config.get("timeout_seconds", 60))
        self.system_prompt = str(
            config.get("system_prompt") or self.default_system_prompt
        ).strip()

    @property
    def is_available(self) -> bool:
        return (
            self.enabled
            and self.provider == "openai_compatible"
            and bool(self.api_key and self.model)
        )

    async def chat(self, prompt: str, purpose: Optional[str] = None) -> str:
        """单轮：system_prompt + 单条 user prompt。"""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        return await self.chat_messages(messages, purpose=purpose)

    async def chat_messages(
        self, messages: List[Dict[str, str]], purpose: Optional[str] = None
    ) -> str:
        """多轮：调用方自行拼好 messages。"""
        if not self.is_available:
            raise RuntimeError(
                f"LLM 未启用或缺少 api_key/model（called_by={self.called_by}），请在系统设置中配置"
            )
        params = {
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout_seconds": self.timeout_seconds,
        }
        async with LLMCallRecorder(
            model=self.model,
            called_by=self.called_by,
            purpose=purpose or self.default_purpose,
            base_url=self.base_url or None,
            request_messages=messages,
            request_params=params,
        ) as rec:
            response_obj, text = await asyncio.to_thread(self._chat_sync, messages)
            rec.record_response(response_text=text, response_obj=response_obj)
            return text

    def _chat_sync(self, messages) -> Tuple[Any, str]:
        import openai

        previous_api_key = getattr(openai, "api_key", None)
        previous_api_base = getattr(openai, "api_base", None)
        openai.api_key = self.api_key
        if self.base_url:
            openai.api_base = self.base_url.rstrip("/")
        try:
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                request_timeout=self.timeout_seconds,
            )
            text = response.choices[0].message.content.strip()
            return response, text
        finally:
            openai.api_key = previous_api_key
            openai.api_base = previous_api_base


class PDFStructureLLMClient(BaseLLMClient):
    called_by = "pdf_structure_llm"
    default_system_prompt = "你是一个PDF题目结构分析专家，负责判断跨页、跨列导致的题目拆分和选项缺失问题。"
    default_temperature = 0.1
    default_purpose = "题目结构 LLM 兜底修复"


class OutlineLLMClient(BaseLLMClient):
    called_by = "outline_llm"
    default_system_prompt = (
        "你是408考研大纲解析专家，负责把大纲文本拆成结构化章节树。"
    )


class ChatLLMClient(BaseLLMClient):
    called_by = "chat_service"
    default_system_prompt = "你是一个专业的408考研学习助手，擅长解释知识点、题目分析与学习规划。"
    default_temperature = 0.7


class DocMetaLLMClient(BaseLLMClient):
    called_by = "doc_meta_llm"
    default_system_prompt = (
        "你是408考研资料元信息提取专家。从试卷/课本首页文本中识别"
        "年份、是真题还是模拟题、来源/辅导机构、试卷名等信息。"
    )
    default_temperature = 0.1
    default_purpose = "文档级元信息提取"


class EnrichLLMClient(BaseLLMClient):
    called_by = "enrich_llm"
    default_system_prompt = (
        "你是408考研内容富化专家。负责为题目生成参考答案与解析、标识所考知识点，"
        "为知识点生成摘要/别名/要点。只输出 JSON，不要解释。"
    )
    default_temperature = 0.3
    default_purpose = "语料富化增强"
