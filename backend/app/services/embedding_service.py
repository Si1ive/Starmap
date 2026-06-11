"""
Embedding 服务

封装文本向量化能力，支持：
- OpenAI text-embedding-ada-002
- 批量 embedding（自动分批）
- 简单的文本预处理
"""

from typing import List, Optional

import openai

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# OpenAI ada-002 单次最大 batch 和 token 限制
MAX_BATCH_SIZE = 100
EMBEDDING_MODEL = "text-embedding-ada-002"
EMBEDDING_DIMENSION = 1536


class EmbeddingService:
    """文本向量化服务"""

    def __init__(self):
        openai.api_key = settings.OPENAI_API_KEY

    async def embed_text(self, text: str) -> List[float]:
        """
        对单段文本生成 embedding

        Args:
            text: 待向量化文本

        Returns:
            1536 维浮点向量
        """
        text = self._preprocess(text)
        if not text:
            return [0.0] * EMBEDDING_DIMENSION

        try:
            response = openai.Embedding.create(
                input=[text],
                model=EMBEDDING_MODEL,
            )
            return response["data"][0]["embedding"]
        except Exception as e:
            logger.error("Embedding 生成失败", error=str(e), text_len=len(text))
            raise

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成 embeddings

        自动按 MAX_BATCH_SIZE 分批调用，保持顺序。

        Args:
            texts: 文本列表

        Returns:
            向量列表（与输入等长、等序）
        """
        preprocessed = [self._preprocess(t) for t in texts]
        all_embeddings: List[List[float]] = []

        for i in range(0, len(preprocessed), MAX_BATCH_SIZE):
            batch = preprocessed[i : i + MAX_BATCH_SIZE]
            # 替换空文本为占位符，避免 API 报错
            placeholders = [bool(t) for t in batch]
            batch = [t if t else " " for t in batch]

            try:
                response = openai.Embedding.create(
                    input=batch,
                    model=EMBEDDING_MODEL,
                )
                embeddings = [item["embedding"] for item in response["data"]]
                # 对占位空文本返回零向量
                for j, has_content in enumerate(placeholders):
                    if not has_content:
                        embeddings[j] = [0.0] * EMBEDDING_DIMENSION
                all_embeddings.extend(embeddings)
            except Exception as e:
                logger.error("批量 Embedding 生成失败", batch_start=i, error=str(e))
                raise

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
