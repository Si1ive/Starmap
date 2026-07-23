"""
OpenAI 单提供商适配（含 timeout/retry）
+
P0 仅接入一个提供商，P1 扩展多提供商切换。
"""

import json
import asyncio
from typing import Optional, Dict, Any, List, Tuple

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ModelAdapter:
    """
    旧版 OpenAI 直接调用适配器。

    保留给尚未迁移的 workflow 节点；新 Agent 节点使用 Pydantic AI 运行时。
    """

    def __init__(self, model: Optional[str] = None):
        self.model = model or settings.OPENAI_MODEL
        self.api_key = settings.OPENAI_API_KEY
        self.max_retries = 3
        self.timeout_seconds = 60

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2000,
        purpose: Optional[str] = None,
    ) -> str:
        """
        调用聊天补全
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            purpose: 调用用途
            
        Returns:
            响应文本
        """
        import openai

        last_error = None
        for attempt in range(self.max_retries):
            try:
                client = openai.AsyncOpenAI(api_key=self.api_key)
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self.timeout_seconds,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                last_error = e
                logger.warning(
                    "模型调用失败，重试中",
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                    error=str(e),
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避

        raise RuntimeError(f"模型调用失败（重试{self.max_retries}次）: {last_error}")

    async def structured_completion(
        self,
        messages: List[Dict[str, str]],
        response_format: type,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> Any:
        """
        结构化输出调用
        
        使用 JSON mode 强制模型返回结构化数据。
        
        Args:
            messages: 消息列表
            response_format: Pydantic model 类
            temperature: 温度参数
            max_tokens: 最大token数
            
        Returns:
            解析后的 Pydantic model 实例
        """
        import openai

        last_error = None
        for attempt in range(self.max_retries):
            try:
                client = openai.AsyncOpenAI(api_key=self.api_key)
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    timeout=self.timeout_seconds,
                )
                text = response.choices[0].message.content or ""
                data = json.loads(text)
                return response_format(**data)
            except Exception as e:
                last_error = e
                logger.warning(
                    "结构化调用失败，重试中",
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                    error=str(e),
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"结构化调用失败（重试{self.max_retries}次）: {last_error}")


# 全局适配器实例（可复用）
model_adapter = ModelAdapter()
