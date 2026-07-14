"""检索 segment 的持久化与向量索引一致性管理。"""

from typing import Any, Dict, List, Optional

from qdrant_client.models import PointIdsList, PointStruct
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.qdrant import QdrantManager, qdrant_manager
from app.models.mysql_models import RetrievalSegment

logger = get_logger(__name__)


class SegmentStore:
    """协调 RetrievalSegment 与 Qdrant 向量点的写入、替换和删除。"""

    def __init__(
        self,
        db: AsyncSession,
        qdrant: QdrantManager = qdrant_manager,
    ):
        self.db = db
        self.qdrant = qdrant

    async def store_segments(
        self,
        *,
        entity_type: str,
        entity_ids: List[str],
        collection: str,
        segments: List[RetrievalSegment],
        qdrant_points: List[PointStruct],
        rebuild: bool,
    ) -> Optional[str]:
        """
        写入新 segments，并在 MySQL 提交成功后清理旧 Qdrant 点。

        新向量写入或 MySQL 提交失败时保留旧索引；旧 Qdrant 点清理失败时，
        MySQL 已只引用新点，检索补全会忽略旧点，同时返回可追溯警告。
        """
        old_qdrant_ids: List[str] = []
        if rebuild:
            old_segments = await self._get_entity_segments(entity_type, entity_ids)
            old_qdrant_ids = [
                segment.qdrant_point_id
                for segment in old_segments
                if segment.qdrant_point_id
            ]

        new_qdrant_ids = [str(point.id) for point in qdrant_points]
        try:
            if qdrant_points:
                self.qdrant.upsert_points(collection, qdrant_points)

            if rebuild:
                await self._delete_segment_rows(entity_type, entity_ids)

            self.db.add_all(segments)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            if new_qdrant_ids:
                try:
                    self._delete_qdrant_points(collection, new_qdrant_ids)
                except Exception as cleanup_error:
                    logger.warning(
                        "新 Qdrant 点回滚清理失败",
                        entity_type=entity_type,
                        entity_ids=entity_ids,
                        error=str(cleanup_error),
                    )
            raise

        if not old_qdrant_ids:
            return None

        try:
            self._delete_qdrant_points(collection, old_qdrant_ids)
        except Exception as cleanup_error:
            logger.warning(
                "旧 Qdrant 点清理失败",
                entity_type=entity_type,
                entity_ids=entity_ids,
                error=str(cleanup_error),
            )
            return str(cleanup_error)[:500]
        return None

    async def delete_segments(
        self,
        entity_type: str,
        entity_ids: List[str],
    ) -> None:
        """删除指定实体的 MySQL segments 与 Qdrant 向量点。"""
        old_segments = await self._get_entity_segments(entity_type, entity_ids)
        collection = self._collection_for_entity(entity_type)
        qdrant_ids = [
            segment.qdrant_point_id
            for segment in old_segments
            if segment.qdrant_point_id
        ]

        if qdrant_ids:
            try:
                self._delete_qdrant_points(collection, qdrant_ids)
            except Exception as error:
                logger.warning("Qdrant 删除失败，继续处理", error=str(error))

        await self._delete_segment_rows(entity_type, entity_ids)

    async def commit_entity_segment_removal(
        self,
        entity_type: str,
        entity_ids: List[str],
    ) -> Dict[str, Any]:
        """
        提交实体变更与 MySQL segment 删除，再清理对应的 Qdrant 点。

        提交失败时 Qdrant 保持不变；Qdrant 清理失败时返回警告状态。
        """
        old_segments = await self._get_entity_segments(entity_type, entity_ids)
        collection = self._collection_for_entity(entity_type)
        old_qdrant_ids = [
            segment.qdrant_point_id
            for segment in old_segments
            if segment.qdrant_point_id
        ]

        try:
            await self._delete_segment_rows(entity_type, entity_ids)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

        result: Dict[str, Any] = {
            "status": "success",
            "segments_count": len(old_segments),
        }
        if not old_qdrant_ids:
            return result

        try:
            self._delete_qdrant_points(collection, old_qdrant_ids)
        except Exception as cleanup_error:
            logger.warning(
                "实体删除后的 Qdrant 点清理失败",
                entity_type=entity_type,
                entity_ids=entity_ids,
                error=str(cleanup_error),
            )
            result["status"] = "warning"
            result["cleanup_warning"] = str(cleanup_error)[:500]
        return result

    async def _get_entity_segments(
        self,
        entity_type: str,
        entity_ids: List[str],
    ) -> List[RetrievalSegment]:
        result = await self.db.execute(
            select(RetrievalSegment).where(
                and_(
                    RetrievalSegment.entity_type == entity_type,
                    RetrievalSegment.entity_id.in_(entity_ids),
                )
            )
        )
        return list(result.scalars().all())

    async def _delete_segment_rows(
        self,
        entity_type: str,
        entity_ids: List[str],
    ) -> None:
        await self.db.execute(
            delete(RetrievalSegment).where(
                and_(
                    RetrievalSegment.entity_type == entity_type,
                    RetrievalSegment.entity_id.in_(entity_ids),
                )
            )
        )

    def _delete_qdrant_points(
        self,
        collection: str,
        point_ids: List[str],
    ) -> None:
        self.qdrant.client.delete(
            collection_name=collection,
            points_selector=PointIdsList(points=point_ids),
        )

    @staticmethod
    def _collection_for_entity(entity_type: str) -> str:
        if entity_type in ("knowledge_point", "canonical_chapter"):
            return QdrantManager.COLLECTION_KNOWLEDGE_SEGMENTS
        return QdrantManager.COLLECTION_QUESTION_SEGMENTS
