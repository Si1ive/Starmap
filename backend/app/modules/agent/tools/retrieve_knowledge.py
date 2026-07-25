"""
retrieve_knowledge 工具适配器
+
调用 RetrievalService 的 RAG 检索，封装为 Tool。
"""

import uuid
from typing import Any, Dict, Optional, List

from app.core.logging import get_logger
from app.modules.retrieval.service import RetrievalService
from ..events import event_store
from ..time_utils import utc_isoformat, utc_now
from .registry import ToolRegistry, ToolSpec

logger = get_logger(__name__)


async def retrieve_knowledge(
    db,
    query: str,
    subject_id: Optional[str] = None,
    chapter_ids: Optional[List[str]] = None,
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
        entity_type: 实体类型（knowledge_point / question）
        limit: 返回结果数量
    
    Returns:
        检索结果字典
    """
    service = RetrievalService(db)
    activity_id = f"activity_{uuid.uuid4().hex[:20]}"
    started_at = utc_now()
    
    logger.info(
        "工具调用: retrieve_knowledge",
        query=query,
        subject_id=subject_id,
        chapter_ids=chapter_ids,
    )
    
    if run_id:
        await event_store.append(
            db,
            run_id,
            "tool.called",
            {
                "activity_id": activity_id,
                "activity_type": "retrieval",
                "title": "检索 408 知识库",
                "detail": f"正在使用混合检索查询“{query[:120]}”",
                "started_at": utc_isoformat(started_at),
                "public_metadata": {
                    "tool": "retrieve_knowledge",
                    "backend": "Qdrant 混合检索 + MySQL 内容索引",
                    "query": query[:200],
                    "subject_id": subject_id,
                    "chapter_ids": chapter_ids or [],
                    "entity_type": entity_type,
                    "limit": limit,
                },
            },
        )
        await db.commit()

    try:
        result = await service.search_with_outline_expansion(
            query=query,
            subject_id=subject_id,
            chapter_ids=chapter_ids,
            entity_type=entity_type,
            mode="hybrid",
            limit=limit,
        )
        
        # 精简结果，只保留关键字段
        simplified = []
        for item in result.get("results", []):
            simplified.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "content": item.get("content", "")[:500],  # 截断
                "source_type": item.get("source_type"),
                "score": item.get("score"),
                "entity_type": item.get("entity_type"),
            })
        
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
                    "id": item.get("id"),
                    "title": item.get("title") or "未命名资料",
                    "source_type": item.get("source_type"),
                    "entity_type": item.get("entity_type"),
                    "score": item.get("score"),
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
                    "activity_type": "retrieval",
                    "title": "检索 408 知识库",
                    "detail": "暂时无法检索相关文档",
                    "status": "failed",
                    "started_at": utc_isoformat(started_at),
                    "completed_at": utc_isoformat(completed_at),
                    "public_metadata": {
                        "tool": "retrieve_knowledge",
                        "backend": "Qdrant 混合检索 + MySQL 内容索引",
                        "query": query[:200],
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
