"""
Embedding 服务

封装文本向量化能力，支持：
- OpenAI text-embedding-ada-002
- 批量 embedding（自动分批）
- 简单的文本预处理
"""

import asyncio
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm_call_recorder import LLMCallRecorder

logger = get_logger(__name__)

# OpenAI ada-002 单次最大 batch 和 token 限制
MAX_BATCH_SIZE = 100
EMBEDDING_MODEL = "text-embedding-ada-002"
EMBEDDING_DIMENSION = 1536


class EmbeddingService:
    """文本向量化服务"""

    def __init__(self):
        import openai
        openai.api_key = settings.OPENAI_API_KEY

    async def embed_text(self, text: str) -> List[float]:
        text = self._preprocess(text)
        if not text:
            return [0.0] * EMBEDDING_DIMENSION

        import openai

        async with LLMCallRecorder(
            model=EMBEDDING_MODEL,
            called_by="embedding_service",
            purpose="单条文本向量化",
            request_messages=[{"role": "input", "content": text}],
            request_params={"batch_size": 1},
        ) as rec:
            response = await asyncio.to_thread(
                openai.Embedding.create, input=[text], model=EMBEDDING_MODEL
            )
            rec.record_response(
                response_text=f"<embedding: {EMBEDDING_DIMENSION}d>",
                response_obj=response,
            )
            return response["data"][0]["embedding"]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        import openai
        preprocessed = [self._preprocess(t) for t in texts]
        all_embeddings: List[List[float]] = []

        for i in range(0, len(preprocessed), MAX_BATCH_SIZE):
            batch = preprocessed[i : i + MAX_BATCH_SIZE]
            placeholders = [bool(t) for t in batch]
            batch = [t if t else " " for t in batch]

            async with LLMCallRecorder(
                model=EMBEDDING_MODEL,
                called_by="embedding_service",
                purpose=f"批量向量化（batch_size={len(batch)}）",
                request_messages=[{"role": "input", "content": f"<{len(batch)} texts>"}],
                request_params={"batch_size": len(batch), "batch_index": i // MAX_BATCH_SIZE},
            ) as rec:
                response = await asyncio.to_thread(
                    openai.Embedding.create, input=batch, model=EMBEDDING_MODEL
                )
                rec.record_response(
                    response_text=f"<{len(batch)} embeddings @{EMBEDDING_DIMENSION}d>",
                    response_obj=response,
                )
                embeddings = [item["embedding"] for item in response["data"]]
                for j, has_content in enumerate(placeholders):
                    if not has_content:
                        embeddings[j] = [0.0] * EMBEDDING_DIMENSION
                all_embeddings.extend(embeddings)

        return all_embeddings

    @staticmethod
    def _preprocess(text: str) -> str:
        """简单预处理：去除多余空白，截断超长文本"""
        if not text:
            return ""
        text = text.strip()
        # ada-002 上限 ~8191 tokens，粗略按 4 字符/token 估算
        max_chars = 8000 * 4
        if len(text) > max_chars:
            text = text[:max_chars]
        return text


# 全局单例
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """获取 Embedding 服务实例"""
    global _embedding_service
    if not _embedding_service:
        _embedding_service = EmbeddingService()
    return _embedding_service
