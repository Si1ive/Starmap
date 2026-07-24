"""
共享 LLM 客户端

把 PDF 结构解析、大纲拆分、问答等多处重复的 OpenAI 兼容调用收敛到一处：
- BaseLLMClient：统一 config 解析、is_available 判断、chat/chat_messages 调用与日志记录
- PDFStructureLLMClient / OutlineLLMClient / ChatLLMClient：各自默认 system_prompt 与 called_by

每次调用创建独立的 openai>=1.x AsyncOpenAI 客户端，因此多配置并存时不会互相覆盖
api_key 或 base_url。
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.monitoring.llm_calls import LLMCallRecorder

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
            cleaned = cleaned[start : end + 1]
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
        self.api_key = str(
            config.get("api_key") or settings.OPENAI_API_KEY or ""
        ).strip()
        self.model = str(config.get("model") or settings.OPENAI_MODEL).strip()
        self.temperature = float(config.get("temperature", self.default_temperature))
        configured_max_tokens = config.get("max_tokens", 2000)
        self.max_tokens = (
            None
            if configured_max_tokens is None
            else int(configured_max_tokens)
        )
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
            "temperature": self.temperature,
            "timeout_seconds": self.timeout_seconds,
        }
        if self.max_tokens is not None:
            params["max_tokens"] = self.max_tokens
        async with LLMCallRecorder(
            model=self.model,
            called_by=self.called_by,
            purpose=purpose or self.default_purpose,
            base_url=self.base_url or None,
            request_messages=messages,
            request_params=params,
        ) as rec:
            response_obj, text = await self._chat(messages)
            rec.record_response(response_text=text, response_obj=response_obj)
            return text

    async def _chat(self, messages) -> Tuple[Any, str]:
        import openai

        client_options: Dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": self.timeout_seconds,
        }
        if self.base_url:
            client_options["base_url"] = self.base_url.rstrip("/")

        client = openai.AsyncOpenAI(**client_options)
        try:
            request_kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
            }
            if self.max_tokens is not None:
                request_kwargs["max_tokens"] = self.max_tokens
            response = await client.chat.completions.create(**request_kwargs)
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("LLM 返回为空")
            text = content.strip()
            return response, text
        finally:
            await client.close()


class PDFStructureLLMClient(BaseLLMClient):
    called_by = "pdf_structure_llm"
    default_system_prompt = (
        "你是一个PDF题目结构分析专家，负责判断跨页、跨列导致的题目拆分和选项缺失问题。"
    )
    default_temperature = 0.1
    default_purpose = "题目结构 LLM 兜底修复"


class OutlineLLMClient(BaseLLMClient):
    called_by = "outline_llm"
    default_system_prompt = "你是408考研大纲解析专家，负责把大纲文本拆成结构化章节树。"
    default_temperature = 0.2

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        super().__init__(config)
        if "max_tokens" not in config:
            self.max_tokens = 16000
        if not config.get("timeout_seconds"):
            self.timeout_seconds = 180


class ChatLLMClient(BaseLLMClient):
    called_by = "chat_service"
    default_system_prompt = "你是一个专业的408考研学习助手，擅长解释知识点、分析题目并根据对话提供练习反馈。"
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
