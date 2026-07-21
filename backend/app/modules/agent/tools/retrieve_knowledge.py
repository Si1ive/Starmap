"""
retrieve_knowledge 工具适配器
+
调用 RetrievalService 的 RAG 检索，封装为 Tool。
"""

from typing import Any, Dict, Optional, List

from app.core.logging import get_logger
from app.modules.retrieval.service import RetrievalService
from .registry import ToolRegistry, ToolSpec

logger = get_logger(__name__)


async def retrieve_knowledge(
    db,
    query: str,
    subject_id: Optional[str] = None,
    chapter_ids: Optional[List[str]] = None,
    entity_type: Optional[str] = None,
    limit: int = 10,
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
    
    logger.info(
        "工具调用: retrieve_knowledge",
        query=query,
        subject_id=subject_id,
        chapter_ids=chapter_ids,
    )
    
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
        
        return {
            "status": "success",
            "query": query,
            "results": simplified,
            "total": len(simplified),
        }
    except Exception as e:
        logger.error("检索失败", query=query, error=str(e))
        return {
            "status": "error",
            "query": query,
            "error": str(e),
            "results": [],
            "total": 0,
        }


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
