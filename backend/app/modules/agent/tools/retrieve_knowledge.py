"""
retrieve_knowledge 工具适配器

调用 RetrievalService 的 RAG 检索，封装为 Tool。
"""

import hashlib
import json
import uuid
from typing import Any, Dict, Optional, List

from sqlalchemy import select

from app.core.logging import get_logger
from app.modules.agent.models import AgentEvent
from app.modules.retrieval.service import RetrievalService
from ..events import event_store
from ..time_utils import utc_isoformat, utc_now
from .registry import ToolRegistry, ToolSpec

logger = get_logger(__name__)


def _agent_result_title(item: Dict[str, Any]) -> str:
    entity = item.get("entity") or {}
    title = item.get("title") or entity.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    content_text = str(item.get("content_text") or "").strip()
    if content_text:
        return content_text[:80]
    return "未命名资料"


def _normalize_agent_result(item: Dict[str, Any]) -> Dict[str, Any]:
    entity = item.get("entity") or {}
    return {
        "entity_id": item.get("entity_id"),
        "entity_type": item.get("entity_type"),
        "entity_title": _agent_result_title(item),
        "entity": {
            "id": entity.get("id") or item.get("entity_id"),
            "type": entity.get("type") or item.get("entity_type"),
            "title": entity.get("title") or _agent_result_title(item),
            "review_status": entity.get("review_status"),
            "status": entity.get("status"),
        },
        "segment_id": item.get("segment_id"),
        "segment_type": item.get("segment_type"),
        "content_text": str(item.get("content_text") or "")[:500],
        "context_text": str(item.get("context_text") or "")[:800],
        "score": item.get("score"),
        "subject_id": item.get("subject_id"),
        "chapter_ids": item.get("chapter_ids") or [],
        "source": item.get("source") or {},
        "question_meta": item.get("question_meta"),
        "knowledge_point_meta": item.get("knowledge_point_meta"),
    }


def _sort_agent_results(
    items: List[Dict[str, Any]],
    *,
    entity_type: Optional[str],
) -> List[Dict[str, Any]]:
    if entity_type is not None:
        return items

    def sort_key(item: Dict[str, Any]) -> tuple[int, float]:
        priority = 0 if item.get("entity_type") == "knowledge_point" else 1
        score = float(item.get("score") or 0.0)
        return (priority, -score)

    return sorted(items, key=sort_key)


def _logical_activity_id(
    *,
    run_id: Optional[str],
    query: str,
    subject_id: Optional[str],
    chapter_ids: Optional[List[str]],
    strict_chapter_scope: bool,
    knowledge_point_ids: Optional[List[str]],
    filters: Optional[Dict[str, Any]],
    exclude_entity_ids: Optional[List[str]],
    entity_type: Optional[str],
) -> str:
    normalized = {
        "tool": "retrieve_knowledge",
        "run_id": run_id or "",
        "query": query.strip(),
        "subject_id": subject_id or "",
        "chapter_ids": sorted(set(chapter_ids or [])),
        "strict_chapter_scope": strict_chapter_scope,
        "knowledge_point_ids": sorted(set(knowledge_point_ids or [])),
        "filters": filters or {},
        "exclude_entity_ids": sorted(set(exclude_entity_ids or [])),
        "entity_type": entity_type or "",
    }
    digest = hashlib.sha1(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"activity_{digest}"


async def _next_attempt_number(
    db,
    *,
    run_id: str,
    logical_activity_id: str,
) -> int:
    result = await db.execute(
        select(AgentEvent)
        .where(
            AgentEvent.run_id == run_id,
            AgentEvent.event_type == "tool.called",
        )
        .order_by(AgentEvent.sequence)
    )
    attempts = 0
    for event in result.scalars().all():
        payload = event.payload or {}
        activity_id = str(
            payload.get("logical_activity_id") or payload.get("activity_id") or ""
        )
        if activity_id == logical_activity_id:
            attempts += 1
    return attempts + 1


async def retrieve_knowledge(
    db,
    query: str,
    subject_id: Optional[str] = None,
    chapter_ids: Optional[List[str]] = None,
    strict_chapter_scope: bool = False,
    knowledge_point_ids: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
    exclude_entity_ids: Optional[List[str]] = None,
    entity_type: Optional[str] = None,
    limit: int = 10,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    检索知识库
    
    Args:
        db: 数据库session
        query: 查询文本
        subject_id: 限定学科ID
        chapter_ids: 限定章节ID列表
        strict_chapter_scope: 是否禁止大纲扩展加入额外章节
        knowledge_point_ids: 限定题目关联的知识点ID列表
        filters: 结构化过滤条件
        exclude_entity_ids: 需要排除的实体ID列表
        entity_type: 实体类型（knowledge_point / question）
        limit: 返回结果数量
    
    Returns:
        检索结果字典
    """
    service = RetrievalService(db)
    attempt_id = f"attempt_{uuid.uuid4().hex[:20]}"
    activity_id = _logical_activity_id(
        run_id=run_id,
        query=query,
        subject_id=subject_id,
        chapter_ids=chapter_ids,
        strict_chapter_scope=strict_chapter_scope,
        knowledge_point_ids=knowledge_point_ids,
        filters=filters,
        exclude_entity_ids=exclude_entity_ids,
        entity_type=entity_type,
    )
    attempt_no = (
        await _next_attempt_number(
            db,
            run_id=run_id,
            logical_activity_id=activity_id,
        )
        if run_id
        else 1
    )
    started_at = utc_now()
    
    logger.info(
        "工具调用: retrieve_knowledge",
        query=query,
        subject_id=subject_id,
        chapter_ids=chapter_ids,
        strict_chapter_scope=strict_chapter_scope,
        knowledge_point_ids=knowledge_point_ids,
        filters=filters,
        exclude_entity_ids=exclude_entity_ids,
    )
    
    if run_id:
        detail = (
            f"正在第 {attempt_no} 次尝试检索“{query[:120]}”"
            if attempt_no > 1
            else f"正在使用混合检索查询“{query[:120]}”"
        )
        await event_store.append(
            db,
            run_id,
            "tool.called",
            {
                "activity_id": activity_id,
                "logical_activity_id": activity_id,
                "attempt_id": attempt_id,
                "attempt_no": attempt_no,
                "activity_type": "retrieval",
                "title": "检索 408 知识库",
                "detail": detail,
                "started_at": utc_isoformat(started_at),
                "public_metadata": {
                    "tool": "retrieve_knowledge",
                    "backend": "Qdrant 混合检索 + MySQL 内容索引",
                    "query": query[:200],
                    "subject_id": subject_id,
                    "chapter_ids": chapter_ids or [],
                    "strict_chapter_scope": strict_chapter_scope,
                    "knowledge_point_ids": knowledge_point_ids or [],
                    "entity_type": entity_type,
                    "filters": filters or {},
                    "exclude_entity_ids": exclude_entity_ids or [],
                    "limit": limit,
                    "attempt_no": attempt_no,
                },
            },
        )
        await db.commit()

    try:
        result = await service.search_with_outline_expansion(
            query=query,
            subject_id=subject_id,
            chapter_ids=chapter_ids,
            strict_chapter_scope=strict_chapter_scope,
            knowledge_point_ids=knowledge_point_ids,
            entity_type=entity_type,
            mode="hybrid",
            limit=limit,
            filters=filters,
            exclude_entity_ids=exclude_entity_ids,
            recall_called_by="agent_rag",
            recall_purpose="Agent RAG 内容向量召回",
        )
        
        normalized = [
            _normalize_agent_result(item)
            for item in result.get("results", [])
        ]
        simplified = _sort_agent_results(normalized, entity_type=entity_type)
        
        response = {
            "status": "success",
            "query": query,
            "results": simplified,
            "total": len(simplified),
            "mode": result.get("mode", "hybrid"),
            "outline_expansion": result.get("outline_expansion") or {},
        }
        if run_id:
            document_summaries = [
                {
                    "id": item.get("entity_id"),
                    "title": item.get("entity_title") or "未命名资料",
                    "entity_type": item.get("entity_type"),
                    "score": item.get("score"),
                    "source": item.get("source") or {},
                }
                for item in simplified[:5]
            ]
            completed_at = utc_now()
            await event_store.append(
                db,
                run_id,
                "tool.result",
                {
                    "activity_id": activity_id,
                    "logical_activity_id": activity_id,
                    "attempt_id": attempt_id,
                    "attempt_no": attempt_no,
                    "activity_type": "retrieval",
                    "title": "检索 408 知识库",
                    "detail": (
                        f"混合检索完成，命中 {len(simplified)} 份资料"
                        if simplified
                        else "没有检索到相关文档"
                    ),
                    "status": "completed",
                    "started_at": utc_isoformat(started_at),
                    "completed_at": utc_isoformat(completed_at),
                    "public_metadata": {
                        "tool": "retrieve_knowledge",
                        "backend": "Qdrant 混合检索 + MySQL 内容索引",
                        "query": query[:200],
                        "total": len(simplified),
                        "documents": document_summaries,
                        "attempt_no": attempt_no,
                        "matched_chapters": (
                            response["outline_expansion"].get("matched_chapters", [])[:5]
                        ),
                    },
                },
            )
            await db.commit()
        return response
    except Exception as e:
        logger.error("检索失败", query=query, error=str(e))
        response = {
            "status": "error",
            "query": query,
            "error": str(e),
            "results": [],
            "total": 0,
        }
        if run_id:
            completed_at = utc_now()
            await event_store.append(
                db,
                run_id,
                "tool.result",
                {
                    "activity_id": activity_id,
                    "logical_activity_id": activity_id,
                    "attempt_id": attempt_id,
                    "attempt_no": attempt_no,
                    "activity_type": "retrieval",
                    "title": "检索 408 知识库",
                    "detail": "暂时无法检索相关文档",
                    "status": "failed",
                    "started_at": utc_isoformat(started_at),
                    "completed_at": utc_isoformat(completed_at),
                    "error": str(e),
                    "public_metadata": {
                        "tool": "retrieve_knowledge",
                        "backend": "Qdrant 混合检索 + MySQL 内容索引",
                        "query": query[:200],
                        "attempt_no": attempt_no,
                    },
                },
            )
            await db.commit()
        return response


# 注册工具
_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "检索查询文本",
        },
        "subject_id": {
            "type": "string",
            "description": "限定学科ID（可选）",
        },
        "chapter_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "限定章节ID列表（可选）",
        },
        "knowledge_point_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "限定题目关联的知识点ID列表（可选）",
        },
        "filters": {
            "type": "object",
            "description": "结构化过滤，例如 difficulty/question_type/tags",
        },
        "exclude_entity_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "需要排除的实体ID列表（可选）",
        },
        "entity_type": {
            "type": "string",
            "enum": ["knowledge_point", "question"],
            "description": "实体类型（可选）",
        },
        "limit": {
            "type": "integer",
            "default": 10,
            "description": "返回结果数量",
        },
    },
    "required": ["query"],
}


def register_retrieve_knowledge(registry: ToolRegistry):
    """注册 retrieve_knowledge 工具"""
    registry.register(
        ToolSpec(
            name="retrieve_knowledge",
            description="从知识库中检索相关知识点或题目，返回检索结果列表",
            parameters=_TOOL_PARAMETERS,
            execute=retrieve_knowledge,
            read_only=True,
        )
    )
