"""
Embedding 服务

封装文本向量化能力，支持：
- OpenAI text-embedding-ada-002
- 批量 embedding（自动分批）
- 简单的文本预处理
"""

from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.monitoring.llm_calls import LLMCallRecorder

logger = get_logger(__name__)

# OpenAI 兼容服务的批量上限不一致；DashScope embedding 单批最多 25 条。
MAX_BATCH_SIZE = 25
# 缺省值（无配置时回退）
DEFAULT_EMBEDDING_PROVIDER = "openai_compatible"
DEFAULT_EMBEDDING_MODEL = "text-embedding-ada-002"
DEFAULT_EMBEDDING_DIMENSION = 1536
# 兼容旧引用
EMBEDDING_MODEL = DEFAULT_EMBEDDING_MODEL
EMBEDDING_DIMENSION = DEFAULT_EMBEDDING_DIMENSION

# 本地 BGE-M3：由独立 infinity 容器提供 OpenAI 兼容接口，走 dense 检索。
LOCAL_BGE_M3_PROVIDER = "local_bge_m3"
DEFAULT_BGE_M3_MODEL = "BAAI/bge-m3"
DEFAULT_BGE_M3_DIMENSION = 1024
# 容器内服务名 + infinity 默认端口，OpenAI 兼容路径在 /v1
DEFAULT_BGE_M3_BASE_URL = "http://bge-m3:7997/v1"
# infinity 不校验 api_key，但 openai SDK 要求非空，填占位符即可。
LOCAL_BGE_M3_API_KEY_PLACEHOLDER = "local-bge-m3"


class EmbeddingService:
    """文本向量化服务（model/维度/api_key/base_url 可由系统配置注入）

    provider:
    - openai_compatible: 调用外部 OpenAI 兼容 embedding 接口
    - local_bge_m3: 调用本机/容器内的 BGE-M3 infinity 服务（同样是 OpenAI 兼容接口，
      只是 base_url 默认指向 bge-m3 容器，且不需要真实 api_key）
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.provider = str(config.get("provider") or DEFAULT_EMBEDDING_PROVIDER).strip()
        self.is_local = self.provider == LOCAL_BGE_M3_PROVIDER

        if self.is_local:
            self.model = str(config.get("model") or DEFAULT_BGE_M3_MODEL).strip()
            self.dimension = int(config.get("dimension") or DEFAULT_BGE_M3_DIMENSION)
            self.base_url = str(config.get("base_url") or DEFAULT_BGE_M3_BASE_URL).strip()
            # infinity 不校验 key，但 openai SDK 要求非空。
            self.api_key = str(config.get("api_key") or LOCAL_BGE_M3_API_KEY_PLACEHOLDER).strip()
        else:
            self.model = str(config.get("model") or DEFAULT_EMBEDDING_MODEL).strip()
            self.dimension = int(config.get("dimension") or DEFAULT_EMBEDDING_DIMENSION)
            self.base_url = str(config.get("base_url") or "").strip()
            self.api_key = str(config.get("api_key") or settings.OPENAI_API_KEY or "").strip()
        self.timeout_seconds = int(config.get("timeout_seconds") or 60)

    async def _create_embedding(self, inputs: List[str]):
        """通过独立的 openai>=1.x 客户端调用兼容向量接口。"""
        import openai

        client_options: Dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": self.timeout_seconds,
        }
        if self.base_url:
            client_options["base_url"] = self.base_url.rstrip("/")

        client = openai.AsyncOpenAI(**client_options)
        try:
            return await client.embeddings.create(
                input=inputs,
                model=self.model,
            )
        finally:
            await client.close()

    @staticmethod
    def _extract_embeddings(response: Any) -> List[List[float]]:
        if hasattr(response, "data"):
            return [list(item.embedding) for item in response.data]
        return [list(item["embedding"]) for item in response["data"]]

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
            response = await self._create_embedding([text])
            rec.record_response(
                response_text=f"<embedding: {self.dimension}d>",
                response_obj=response,
            )
            return self._extract_embeddings(response)[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
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
                response = await self._create_embedding(batch)
                rec.record_response(
                    response_text=f"<{len(batch)} embeddings @{self.dimension}d>",
                    response_obj=response,
                )
                embeddings = self._extract_embeddings(response)
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
        str(config.get("provider") or DEFAULT_EMBEDDING_PROVIDER),
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
        from app.modules.operations.settings_service import SystemSettingsService
        runtime_settings = await SystemSettingsService(db).load()
        cfg = runtime_settings.get("embedding", {}) or {}
    except Exception as e:
        logger.warning("读取 embedding 配置失败，回退缺省值", error=str(e))
        cfg = {}
    return get_embedding_service(cfg)
