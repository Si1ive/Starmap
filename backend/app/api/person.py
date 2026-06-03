"""
人物API路由

提供人物相关的RESTful API：
- GET /persons/{person_id} - 人物详情
- GET /persons/{person_id}/relations - 人物关系
"""

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from app.middleware.error_handler import NotFoundException
from app.models.person import (
    Person,
    PersonRelationGraph,
    SimilarPersonResult
)
from app.services.person_service import PersonService, get_person_service

router = APIRouter(prefix="/persons", tags=["人物"])


@router.get("/{person_id}", response_model=Person)
async def get_person_detail(
    person_id: str = Path(..., description="人物ID"),
    service: PersonService = Depends(get_person_service)
):
    """
    获取人物详情
    
    返回人物的完整信息，包括基本信息、分类、描述等。
    数据优先从缓存获取，缓存未命中查询Neo4j图数据库。
    
    - **person_id**: 人物唯一标识（如 jay-chou）
    """
    person = await service.get_person_by_id(person_id)
    
    if not person:
        raise NotFoundException(resource="人物", identifier=person_id)
    
    return person


@router.get("/{person_id}/relations", response_model=PersonRelationGraph)
async def get_person_relations(
    person_id: str = Path(..., description="人物ID"),
    depth: int = Query(1, ge=1, le=3, description="关系深度（1-3）"),
    relation_type: Optional[str] = Query(None, description="关系类型过滤"),
    service: PersonService = Depends(get_person_service)
):
    """
    获取人物关系图谱
    
    返回指定人物的关系网络，包含节点和边数据，
    可用于前端力导向图可视化。
    
    - **person_id**: 中心人物ID
    - **depth**: 关系深度，1表示直接关系，最大3
    - **relation_type**: 可选的关系类型过滤（如 spouse/collaborate）
    """
    # 验证人物存在
    person = await service.get_person_by_id(person_id)
    if not person:
        raise NotFoundException(resource="人物", identifier=person_id)
    
    return await service.get_person_relations(
        person_id=person_id,
        depth=depth,
        relation_type=relation_type
    )


@router.get("/{person_id}/similar", response_model=SimilarPersonResult)
async def get_similar_persons(
    person_id: str = Path(..., description="人物ID"),
    limit: int = Query(5, ge=1, le=20, description="返回数量"),
    service: PersonService = Depends(get_person_service)
):
    """
    获取相似人物推荐
    
    基于共同关系数量计算相似度，返回最相似的人物列表。
    
    - **person_id**: 参考人物ID
    - **limit**: 返回数量（1-20）
    """
    # 验证人物存在
    person = await service.get_person_by_id(person_id)
    if not person:
        raise NotFoundException(resource="人物", identifier=person_id)
    
    return await service.get_similar_persons(person_id, limit)
