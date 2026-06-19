"""
LLM 调用记录器

封装 OpenAI 兼容 API 调用，记录每次调用的请求/响应/Token/耗时/成本到 llm_call_logs。

设计原则：
- 调用方只关心 prompt → text，记录是 side effect
- 记录失败不能影响业务调用
- 记录与业务在同一事务外（独立 session），避免回滚污染
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.mysql import mysql_client
from app.models.mysql_models import LLMCallLog

logger = get_logger(__name__)

# 简易价格表（USD per 1K tokens）；用户可在系统设置覆盖
DEFAULT_PRICING: Dict[str, Dict[str, float]] = {
    "gpt-4o": {"prompt": 0.0025, "completion": 0.01},
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
    "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
    "gpt-4": {"prompt": 0.03, "completion": 0.06},
    "gpt-3.5-turbo": {"prompt": 0.0005, "completion": 0.0015},
    "deepseek-chat": {"prompt": 0.00027, "completion": 0.0011},
    "deepseek-reasoner": {"prompt": 0.00055, "completion": 0.0022},
    "qwen-turbo": {"prompt": 0.0003, "completion": 0.0006},
    "qwen-plus": {"prompt": 0.0008, "completion": 0.002},
    "qwen-max": {"prompt": 0.0024, "completion": 0.0096},
}

MAX_PROMPT_PERSIST_LEN = 20000   # request_messages 单条文本上限（够看清输入构造）
MAX_RESPONSE_PERSIST_LEN = 20000 # response_text 上限（够看清输出是否符合预期）


def _generate_id() -> str:
    return uuid.uuid4().hex[:32]


def _truncate(text: Optional[str], limit: int) -> Optional[str]:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated, total {len(text)}]"


def _truncate_messages(messages: List[Dict[str, Any]], limit: int = MAX_PROMPT_PERSIST_LEN) -> List[Dict[str, Any]]:
    safe: List[Dict[str, Any]] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "user"))[:32]
        content = msg.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        safe.append({"role": role, "content": _truncate(str(content), limit)})
    return safe


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = DEFAULT_PRICING.get(model.lower())
    if not rates:
        # 模糊匹配前缀
        for key, value in DEFAULT_PRICING.items():
            if model.lower().startswith(key):
                rates = value
                break
    if not rates:
        return 0.0
    return round(
        prompt_tokens / 1000.0 * rates["prompt"] + completion_tokens / 1000.0 * rates["completion"],
        6,
    )


class LLMCallRecorder:
    """
    记录 LLM 调用到数据库。

    用法 1（推荐，async 上下文）：
        async with LLMCallRecorder(model=..., called_by="chat_service") as rec:
            response = await client.chat.completions.create(...)
            rec.record_response(response_obj=response, response_text=text)

    用法 2（异常自动记录）：
        try:
            ...
        except Exception as e:
            rec.record_error(e)
    """

    def __init__(
        self,
        model: str,
        called_by: str,
        purpose: Optional[str] = None,
        provider: str = "openai_compatible",
        base_url: Optional[str] = None,
        request_messages: Optional[List[Dict[str, Any]]] = None,
        request_params: Optional[Dict[str, Any]] = None,
    ):
        self.id = _generate_id()
        self.model = model
        self.called_by = called_by
        self.purpose = purpose
        self.provider = provider
        self.base_url = base_url
        self.request_messages = _truncate_messages(request_messages or [])
        self.request_params = request_params or {}

        self._start_time: Optional[float] = None
        self._latency_ms = 0
        self._status = "success"
        self._error_msg: Optional[str] = None
        self._response_text: Optional[str] = None
        self._response_full: Optional[Dict[str, Any]] = None
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0
        self._cost_usd = 0.0
        self._finalized = False

    async def __aenter__(self) -> "LLMCallRecorder":
        self._start_time = time.perf_counter()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc is not None and not self._finalized:
            self.record_error(exc)
        await self.persist()
        return False  # 不吞异常

    def record_response(
        self,
        response_text: Optional[str] = None,
        response_obj: Any = None,
    ) -> None:
        """从 OpenAI 风格的响应对象抽取 token 用量；response_text 是抽取后的文本。"""
        self._response_text = _truncate(response_text or "", MAX_RESPONSE_PERSIST_LEN)
        self._latency_ms = int((time.perf_counter() - (self._start_time or time.perf_counter())) * 1000)

        usage = None
        full: Optional[Dict[str, Any]] = None

        if response_obj is not None:
            try:
                # openai>=1.x 返回的是 pydantic-style；旧版本是 dict
                if hasattr(response_obj, "model_dump"):
                    full = response_obj.model_dump()
                elif hasattr(response_obj, "to_dict"):
                    full = response_obj.to_dict()
                elif isinstance(response_obj, dict):
                    full = response_obj
            except Exception:
                full = None

        if full:
            usage = full.get("usage") if isinstance(full, dict) else None

        if usage:
            self._prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            self._completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            self._total_tokens = int(usage.get("total_tokens", self._prompt_tokens + self._completion_tokens) or 0)

        self._cost_usd = _estimate_cost(self.model, self._prompt_tokens, self._completion_tokens)
        self._response_full = self._truncate_full_dump(full) if full else None
        self._status = "success"

    def record_error(self, exc: Exception) -> None:
        self._latency_ms = int((time.perf_counter() - (self._start_time or time.perf_counter())) * 1000)
        msg = str(exc)
        self._error_msg = msg[:2000]
        self._status = "timeout" if "timeout" in msg.lower() else "error"

    @staticmethod
    def _truncate_full_dump(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            text_repr = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            return {"_serialization_error": True}
        if len(text_repr) <= MAX_RESPONSE_PERSIST_LEN:
            return payload
        return {"_truncated": True, "_excerpt": text_repr[:MAX_RESPONSE_PERSIST_LEN]}

    async def persist(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        try:
            async with mysql_client.session() as session:
                row = LLMCallLog(
                    id=self.id,
                    provider=self.provider,
                    base_url=self.base_url,
                    model=self.model,
                    called_by=self.called_by,
                    purpose=self.purpose,
                    request_messages=self.request_messages,
                    request_params=self.request_params,
                    response_text=self._response_text,
                    response_full=self._response_full,
                    prompt_tokens=self._prompt_tokens,
                    completion_tokens=self._completion_tokens,
                    total_tokens=self._total_tokens,
                    cost_usd=self._cost_usd,
                    latency_ms=self._latency_ms,
                    status=self._status,
                    error_msg=self._error_msg,
                )
                session.add(row)
                await session.commit()
        except Exception as e:
            # 记录失败绝不影响业务
            logger.error("LLM 调用日志写入失败", error=str(e), call_id=self.id)


# ===== 查询 =====


async def list_llm_calls(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    model: Optional[str] = None,
    status: Optional[str] = None,
    called_by: Optional[str] = None,
    keyword: Optional[str] = None,
) -> Dict[str, Any]:
    """分页查询 LLM 调用列表"""
    query = select(LLMCallLog).order_by(LLMCallLog.created_at.desc())
    count_query = select(func.count(LLMCallLog.id))

    if model:
        query = query.where(LLMCallLog.model == model)
        count_query = count_query.where(LLMCallLog.model == model)
    if status:
        query = query.where(LLMCallLog.status == status)
        count_query = count_query.where(LLMCallLog.status == status)
    if called_by:
        query = query.where(LLMCallLog.called_by == called_by)
        count_query = count_query.where(LLMCallLog.called_by == called_by)
    if keyword:
        like = f"%{keyword}%"
        query = query.where(LLMCallLog.response_text.like(like))
        count_query = count_query.where(LLMCallLog.response_text.like(like))

    total = (await session.execute(count_query)).scalar_one()
    rows = (await session.execute(
        query.offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return {
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
        "items": [_log_to_summary(row) for row in rows],
    }


async def get_llm_call_detail(session: AsyncSession, call_id: str) -> Optional[Dict[str, Any]]:
    row = await session.get(LLMCallLog, call_id)
    if not row:
        return None
    return _log_to_detail(row)


async def get_llm_call_stats(session: AsyncSession, hours: int = 24) -> Dict[str, Any]:
    """汇总最近 hours 小时的 LLM 调用情况。"""
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(hours=hours)

    base_query = select(LLMCallLog).where(LLMCallLog.created_at >= since)

    rows = (await session.execute(base_query)).scalars().all()

    total = len(rows)
    success = sum(1 for r in rows if r.status == "success")
    error = total - success
    total_tokens = sum(int(r.total_tokens or 0) for r in rows)
    total_cost = float(sum(float(r.cost_usd or 0) for r in rows))
    latencies = sorted([int(r.latency_ms or 0) for r in rows if r.latency_ms])

    def percentile(arr: List[int], p: float) -> int:
        if not arr:
            return 0
        idx = int(len(arr) * p)
        return arr[min(idx, len(arr) - 1)]

    by_model: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        m = r.model or "unknown"
        slot = by_model.setdefault(m, {"count": 0, "tokens": 0, "cost_usd": 0.0, "errors": 0})
        slot["count"] += 1
        slot["tokens"] += int(r.total_tokens or 0)
        slot["cost_usd"] += float(r.cost_usd or 0)
        if r.status != "success":
            slot["errors"] += 1
    by_model_list = [
        {"model": k, **v, "cost_usd": round(v["cost_usd"], 6)}
        for k, v in sorted(by_model.items(), key=lambda kv: kv[1]["count"], reverse=True)
    ]

    return {
        "window_hours": hours,
        "total_calls": total,
        "success_calls": success,
        "error_calls": error,
        "error_rate": round(error / total, 4) if total else 0,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "p50_latency_ms": percentile(latencies, 0.5),
        "p95_latency_ms": percentile(latencies, 0.95),
        "p99_latency_ms": percentile(latencies, 0.99),
        "by_model": by_model_list,
    }


async def delete_llm_calls(
    session: AsyncSession,
    older_than_days: Optional[int] = None,
    ids: Optional[List[str]] = None,
) -> int:
    from sqlalchemy import delete as sa_delete
    from datetime import timedelta

    if ids:
        result = await session.execute(
            sa_delete(LLMCallLog).where(LLMCallLog.id.in_(ids))
        )
        await session.commit()
        return int(result.rowcount or 0)

    if older_than_days is not None and older_than_days >= 0:
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        result = await session.execute(
            sa_delete(LLMCallLog).where(LLMCallLog.created_at < cutoff)
        )
        await session.commit()
        return int(result.rowcount or 0)

    return 0


def _log_to_summary(row: LLMCallLog) -> Dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "model": row.model,
        "called_by": row.called_by,
        "purpose": row.purpose,
        "status": row.status,
        "prompt_tokens": int(row.prompt_tokens or 0),
        "completion_tokens": int(row.completion_tokens or 0),
        "total_tokens": int(row.total_tokens or 0),
        "cost_usd": float(row.cost_usd or 0),
        "latency_ms": int(row.latency_ms or 0),
        "error_msg": row.error_msg,
        "created_at": (row.created_at.isoformat() + "Z") if row.created_at else None,
    }


def _log_to_detail(row: LLMCallLog) -> Dict[str, Any]:
    summary = _log_to_summary(row)
    summary.update({
        "base_url": row.base_url,
        "request_messages": row.request_messages,
        "request_params": row.request_params,
        "response_text": row.response_text,
        "response_full": row.response_full,
    })
    return summary
