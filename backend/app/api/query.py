"""
查询API路由

提供搜索相关的RESTful API：
- GET /persons/search - 人物搜索
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.models.person import PersonSearchResult
from app.services.person_service import PersonService, get_person_service

router = APIRouter(tags=["查询"])


@router.get("/persons/search", response_model=PersonSearchResult)
async def search_persons(
    q: str = Query(
        ...,
        description="搜索关键词",
        min_length=1,
        max_length=100
    ),
    category: Optional[str] = Query(
        "all",
        description="分类过滤（actor/singer/director/all）"
    ),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    service: PersonService = Depends(get_person_service)
):
    """
    搜索艺人信息
    
    支持按姓名、别名、描述进行全文搜索，可按分类过滤。
    结果包含分页信息，默认每页20条。
    
    - **q**: 搜索关键词（必填，1-100字符）
    - **category**: 分类过滤，可选 actor/singer/director/all
    - **page**: 页码，从1开始
    - **page_size**: 每页数量，1-100
    
    **示例**: `/persons/search?q=周杰伦&category=singer&page=1`
    """
    return await service.search_persons(
        keyword=q,
        category=category if category != "all" else None,
        page=page,
        page_size=page_size
    )
