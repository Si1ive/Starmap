"""
Qdrant 向量数据库连接封装

提供 collection 管理、向量存储和检索功能。
Phase 0: 基础连接和 collection 管理。
Phase 3: 完整的 dense/sparse hybrid 检索。
"""

from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue,
    PayloadSchemaType,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class QdrantConnectionError(Exception):
    """Qdrant 连接异常"""
    pass


class QdrantManager:
    """
    Qdrant 客户端封装

    支持：
    - 连接管理
    - collection 创建/检查
    - 向量存储与检索（Phase 3 扩展）
    """

    # collection 名称常量
    COLLECTION_KNOWLEDGE_SEGMENTS = "knowledge_segments"
    COLLECTION_QUESTION_SEGMENTS = "question_segments"

    def __init__(self):
        self._client: Optional[QdrantClient] = None
        self._host = settings.QDRANT_HOST
        self._port = settings.QDRANT_PORT

    def connect(self) -> None:
        """建立 Qdrant 连接"""
        try:
            self._client = QdrantClient(host=self._host, port=self._port)
            # 验证连接
            collections = self._client.get_collections()
            logger.info(
                "Qdrant 连接成功",
                host=self._host,
                port=self._port,
                collections_count=len(collections.collections),
            )
        except Exception as e:
            logger.error("Qdrant 连接失败", error=str(e), host=self._host, port=self._port)
            raise QdrantConnectionError(f"无法连接到 Qdrant: {e}")

    def close(self) -> None:
        """关闭连接"""
        if self._client:
            self._client.close()
            self._client = None
        logger.info("Qdrant 连接已关闭")

    def health_check(self) -> bool:
        """健康检查"""
        if not self._client:
            return False
        try:
            self._client.get_collections()
            return True
        except Exception:
            return False

    @property
    def client(self) -> QdrantClient:
        """获取原生客户端"""
        if not self._client:
            self.connect()
        return self._client

    # ========== Collection 管理 ==========

    def ensure_collection(
        self,
        name: str,
        vector_size: int = 1536,
        distance: Distance = Distance.COSINE,
    ) -> None:
        """确保 collection 存在，不存在则创建"""
        try:
            collections = self._client.get_collections()
            existing = {c.name for c in collections.collections}
            if name not in existing:
                self._client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=vector_size, distance=distance),
                )
                logger.info("Qdrant collection 已创建", name=name, vector_size=vector_size)
            else:
                logger.debug("Qdrant collection 已存在", name=name)
        except Exception as e:
            logger.error("Qdrant collection 创建失败", name=name, error=str(e))
            raise

    # 需要建 payload 索引的字段 → 索引类型（用于结构化过滤）
    _PAYLOAD_INDEXES = {
        "subject_id": PayloadSchemaType.KEYWORD,
        "chapter_ids": PayloadSchemaType.KEYWORD,
        "segment_type": PayloadSchemaType.KEYWORD,
        "exam_scope": PayloadSchemaType.KEYWORD,
        "difficulty": PayloadSchemaType.KEYWORD,
        "question_type": PayloadSchemaType.KEYWORD,
        "tags": PayloadSchemaType.KEYWORD,
        "answer_source": PayloadSchemaType.KEYWORD,
        "exam_year": PayloadSchemaType.INTEGER,
    }

    def ensure_payload_indexes(self, name: str) -> None:
        """为 collection 建结构化过滤所需的 payload 索引（已存在则忽略）。"""
        for field, schema in self._PAYLOAD_INDEXES.items():
            try:
                self._client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=schema,
                )
            except Exception as e:
                # 已存在或并发创建时 Qdrant 报错，可安全忽略
                logger.debug("payload 索引创建跳过", collection=name, field=field, error=str(e))

    def init_default_collections(self, vector_size: int = 1536) -> None:
        """初始化默认 collections + payload 索引"""
        self.ensure_collection(self.COLLECTION_KNOWLEDGE_SEGMENTS, vector_size)
        self.ensure_collection(self.COLLECTION_QUESTION_SEGMENTS, vector_size)
        self.ensure_payload_indexes(self.COLLECTION_KNOWLEDGE_SEGMENTS)
        self.ensure_payload_indexes(self.COLLECTION_QUESTION_SEGMENTS)

    def collection_info(self, name: str) -> Optional[Dict[str, Any]]:
        """获取 collection 信息"""
        try:
            info = self.client.get_collection(name)
            return {
                "name": name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status,
            }
        except Exception:
            return None

    # ========== 向量操作（Phase 3 扩展） ==========

    def upsert_points(
        self,
        collection_name: str,
        points: List[PointStruct],
    ) -> None:
        """批量写入向量点"""
        self.client.upsert(collection_name=collection_name, points=points)
        logger.info("向量写入完成", collection=collection_name, count=len(points))

    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        limit: int = 10,
        query_filter: Optional[Filter] = None,
    ) -> List[Dict[str, Any]]:
        """向量检索"""
        results = self.client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=limit,
            query_filter=query_filter,
        )
        return [
            {
                "id": hit.id,
                "score": hit.score,
                "payload": hit.payload,
            }
            for hit in results
        ]


# 全局实例
qdrant_manager = QdrantManager()


def get_qdrant_client() -> QdrantManager:
    """获取 Qdrant 客户端（依赖注入用）"""
    if not qdrant_manager._client:
        qdrant_manager.connect()
    return qdrant_manager
