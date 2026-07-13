"""
向量召回记录器

记录每次 Qdrant 章节召回的入参（query）、top-N 结果与分数到 vector_recall_logs，
供分析召回质量、命中率、多 top 结果对比。

设计原则（仿 LLMCallRecorder）：
- 调用方只关心召回结果，记录是 side effect
- 记录失败绝不影响业务召回
- 记录用独立 session，避免污染业务事务
"""

import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.mysql import mysql_client
from app.models.mysql_models import VectorRecallLog

logger = get_logger(__name__)

MAX_QUERY_PERSIST_LEN = 4000


def _generate_id() -> str:
    return uuid.uuid4().hex[:32]


def _truncate(text: Optional[str], limit: int) -> Optional[str]:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated, total {len(text)}]"


class VectorRecallRecorder:
    """记录一次向量召回到数据库。

    用法：
        rec = VectorRecallRecorder(called_by="question", query_text=..., ...)
        rec.start()
        ... 执行召回 ...
        rec.record_results(candidates, threshold=VECTOR_MATCH_THRESHOLD)
        await rec.persist()
    """

    def __init__(
        self,
        called_by: str,
        query_text: str,
        purpose: Optional[str] = None,
        query_entity_id: Optional[str] = None,
        subject_id: Optional[str] = None,
    ):
        self.id = _generate_id()
        self.called_by = called_by
        self.purpose = purpose
        self.query_text = _truncate(query_text, MAX_QUERY_PERSIST_LEN)
        self.query_entity_id = query_entity_id
        self.subject_id = subject_id

        self._start_time: Optional[float] = None
        self._latency_ms = 0
        self._top_results: List[Dict[str, Any]] = []
        self._top_score = 0.0
        self._result_count = 0
        self._threshold_hit = False
        self._status = "hit"
        self._error_msg: Optional[str] = None
        self._finalized = False

    def start(self) -> "VectorRecallRecorder":
        self._start_time = time.perf_counter()
        return self

    def _elapsed_ms(self) -> int:
        return int((time.perf_counter() - (self._start_time or time.perf_counter())) * 1000)

    def record_results(
        self,
        candidates: List[Dict[str, Any]],
        threshold: float = 0.0,
        chapter_name_map: Optional[Dict[str, str]] = None,
    ) -> None:
        """candidates: _match_by_vector_search 聚合后的候选，含 chapter_id/relevance/is_primary。"""
        self._latency_ms = self._elapsed_ms()
        name_map = chapter_name_map or {}
        top: List[Dict[str, Any]] = []
        for rank, c in enumerate(candidates):
            score = float(c.get("relevance", 0) or 0)
            top.append({
                "rank": rank,
                "chapter_id": c.get("chapter_id"),
                "chapter_name": name_map.get(c.get("chapter_id")),
                "score": round(score, 4),
                "is_primary": bool(c.get("is_primary")),
            })
        self._top_results = top
        self._result_count = len(top)
        self._top_score = top[0]["score"] if top else 0.0
        self._threshold_hit = bool(top) and self._top_score >= threshold
        self._status = "hit" if top else "miss"

    def record_error(self, exc: Exception) -> None:
        self._latency_ms = self._elapsed_ms()
        self._error_msg = str(exc)[:2000]
        self._status = "error"

    async def persist(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        try:
            async with mysql_client.session() as session:
                row = VectorRecallLog(
                    id=self.id,
                    called_by=self.called_by,
                    purpose=self.purpose,
                    query_text=self.query_text,
                    query_entity_id=self.query_entity_id,
                    subject_id=self.subject_id,
                    top_results=self._top_results,
                    top_score=self._top_score,
                    result_count=self._result_count,
                    threshold_hit=self._threshold_hit,
                    latency_ms=self._latency_ms,
                    status=self._status,
                    error_msg=self._error_msg,
                )
                session.add(row)
                await session.commit()
        except Exception as e:
            logger.error("向量召回日志写入失败", error=str(e), recall_id=self.id)


# ===== 查询 =====


async def list_vector_recalls(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    called_by: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
) -> Dict[str, Any]:
    query = select(VectorRecallLog).order_by(VectorRecallLog.created_at.desc())
    count_query = select(func.count(VectorRecallLog.id))

    if called_by:
        query = query.where(VectorRecallLog.called_by == called_by)
        count_query = count_query.where(VectorRecallLog.called_by == called_by)
    if status:
        query = query.where(VectorRecallLog.status == status)
        count_query = count_query.where(VectorRecallLog.status == status)
    if keyword:
        like = f"%{keyword}%"
        query = query.where(VectorRecallLog.query_text.like(like))
        count_query = count_query.where(VectorRecallLog.query_text.like(like))

    total = (await session.execute(count_query)).scalar_one()
    rows = (await session.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return {
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
        "items": [_recall_to_dict(row) for row in rows],
    }


async def get_vector_recall_stats(session: AsyncSession, hours: int = 24) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(hours=hours)
    rows = (await session.execute(
        select(VectorRecallLog).where(VectorRecallLog.created_at >= since)
    )).scalars().all()

    total = len(rows)
    hits = sum(1 for r in rows if r.status == "hit")
    misses = sum(1 for r in rows if r.status == "miss")
    errors = sum(1 for r in rows if r.status == "error")
    threshold_hits = sum(1 for r in rows if r.threshold_hit)
    scores = [float(r.top_score or 0) for r in rows if r.status == "hit"]
    latencies = sorted(int(r.latency_ms or 0) for r in rows if r.latency_ms)

    def percentile(arr: List[int], p: float) -> int:
        if not arr:
            return 0
        idx = int(len(arr) * p)
        return arr[min(idx, len(arr) - 1)]

    return {
        "window_hours": hours,
        "total_recalls": total,
        "hit_count": hits,
        "miss_count": misses,
        "error_count": errors,
        # 命中率：有召回结果的比例
        "hit_rate": round(hits / total, 4) if total else 0,
        # 有效召回率：最高分达到采信阈值的比例
        "threshold_hit_rate": round(threshold_hits / total, 4) if total else 0,
        "avg_top_score": round(sum(scores) / len(scores), 4) if scores else 0,
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "p95_latency_ms": percentile(latencies, 0.95),
    }


async def delete_vector_recalls(
    session: AsyncSession,
    older_than_days: Optional[int] = None,
) -> int:
    from sqlalchemy import delete as sa_delete

    if older_than_days is not None and older_than_days >= 0:
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        result = await session.execute(
            sa_delete(VectorRecallLog).where(VectorRecallLog.created_at < cutoff)
        )
        await session.commit()
        return int(result.rowcount or 0)
    return 0


def _recall_to_dict(row: VectorRecallLog) -> Dict[str, Any]:
    return {
        "id": row.id,
        "called_by": row.called_by,
        "purpose": row.purpose,
        "query_text": row.query_text,
        "query_entity_id": row.query_entity_id,
        "subject_id": row.subject_id,
        "top_results": row.top_results or [],
        "top_score": float(row.top_score or 0),
        "result_count": int(row.result_count or 0),
        "threshold_hit": bool(row.threshold_hit),
        "latency_ms": int(row.latency_ms or 0),
        "status": row.status,
        "error_msg": row.error_msg,
        "created_at": (row.created_at.isoformat() + "Z") if row.created_at else None,
    }
