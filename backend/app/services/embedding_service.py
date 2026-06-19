"""
Embedding 服务

封装文本向量化能力，支持：
- OpenAI text-embedding-ada-002
- 批量 embedding（自动分批）
- 简单的文本预处理
"""

import asyncio
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm_call_recorder import LLMCallRecorder

logger = get_logger(__name__)

# OpenAI ada-002 单次最大 batch 和 token 限制
MAX_BATCH_SIZE = 100
# 缺省值（无配置时回退）
DEFAULT_EMBEDDING_MODEL = "text-embedding-ada-002"
DEFAULT_EMBEDDING_DIMENSION = 1536
# 兼容旧引用
EMBEDDING_MODEL = DEFAULT_EMBEDDING_MODEL
EMBEDDING_DIMENSION = DEFAULT_EMBEDDING_DIMENSION


class EmbeddingService:
    """文本向量化服务（model/维度/api_key/base_url 可由系统配置注入）"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.model = str(config.get("model") or DEFAULT_EMBEDDING_MODEL).strip()
        self.dimension = int(config.get("dimension") or DEFAULT_EMBEDDING_DIMENSION)
        self.api_key = str(config.get("api_key") or settings.OPENAI_API_KEY or "").strip()
        self.base_url = str(config.get("base_url") or "").strip()

    def _create_embedding(self, inputs: List[str]):
        """同步调用，save-restore openai 全局变量。"""
        import openai

        previous_api_key = getattr(openai, "api_key", None)
        previous_api_base = getattr(openai, "api_base", None)
        openai.api_key = self.api_key
        if self.base_url:
            openai.api_base = self.base_url.rstrip("/")
        try:
            return openai.Embedding.create(input=inputs, model=self.model)
        finally:
            openai.api_key = previous_api_key
            openai.api_base = previous_api_base

    async def embed_text(self, text: str) -> List[float]:
        text = self._preprocess(text)
        if not text:
            return [0.0] * self.dimension

        async with LLMCallRecorder(
            model=self.model,
            called_by="embedding_service",
            purpose="单条文本向量化",
            base_url=self.base_url or None,
            request_messages=[{"role": "input", "content": text}],
            request_params={"batch_size": 1},
        ) as rec:
            response = await asyncio.to_thread(self._create_embedding, [text])
            rec.record_response(
                response_text=f"<embedding: {self.dimension}d>",
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
                model=self.model,
                called_by="embedding_service",
                purpose=f"批量向量化（batch_size={len(batch)}）",
                base_url=self.base_url or None,
                request_messages=[{"role": "input", "content": f"<{len(batch)} texts>"}],
                request_params={"batch_size": len(batch), "batch_index": i // MAX_BATCH_SIZE},
            ) as rec:
                response = await asyncio.to_thread(self._create_embedding, batch)
                rec.record_response(
                    response_text=f"<{len(batch)} embeddings @{self.dimension}d>",
                    response_obj=response,
                )
                embeddings = [item["embedding"] for item in response["data"]]
                for j, has_content in enumerate(placeholders):
                    if not has_content:
                        embeddings[j] = [0.0] * self.dimension
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


# 全局单例（按 config 指纹缓存，配置变更时自动重建）
_embedding_service: Optional[EmbeddingService] = None
_embedding_fingerprint: Optional[tuple] = None


def get_embedding_service(config: Optional[Dict[str, Any]] = None) -> EmbeddingService:
    """获取 Embedding 服务实例。

    传入 config（来自系统设置的 embedding 块）时，按 model/dimension/api_key/base_url
    指纹缓存；指纹变化则重建，确保配置即时生效。无 config 时回退环境变量缺省值。
    """
    global _embedding_service, _embedding_fingerprint
    config = config or {}
    fingerprint = (
        str(config.get("model") or DEFAULT_EMBEDDING_MODEL),
        int(config.get("dimension") or DEFAULT_EMBEDDING_DIMENSION),
        str(config.get("api_key") or settings.OPENAI_API_KEY or ""),
        str(config.get("base_url") or ""),
    )
    if _embedding_service is None or _embedding_fingerprint != fingerprint:
        _embedding_service = EmbeddingService(config)
        _embedding_fingerprint = fingerprint
    return _embedding_service


async def get_embedding_service_from_settings(db) -> EmbeddingService:
    """从系统设置读取 embedding 配置并构造服务（带 db 的调用方用）。"""
    try:
        from app.services.system_settings_service import SystemSettingsService
        runtime_settings = await SystemSettingsService(db).load()
        cfg = runtime_settings.get("embedding", {}) or {}
    except Exception as e:
        logger.warning("读取 embedding 配置失败，回退缺省值", error=str(e))
        cfg = {}
    return get_embedding_service(cfg)
