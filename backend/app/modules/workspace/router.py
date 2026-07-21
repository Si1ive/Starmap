"""
Workspace Router：线程管理 + 产物管理
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.mysql import mysql_client

logger = get_logger(__name__)

router = APIRouter(prefix="/workspace", tags=["Workspace"])


def get_db():
    return mysql_client.session()


@router.get("/threads")
async def list_workspace_threads(
    limit: int = Query(20, ge=1, le=100),
    user_id: str = "user_test",
    db: AsyncSession = Depends(get_db),
):
    """列出工作台的线程（Agent Router 已提供，这里作为别名）"""
    from app.modules.agent.service import AgentService
    async with db:
        service = AgentService(db)
        threads = await service.list_threads(user_id, limit=limit)
        return {
            "items": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "created_at": t.created_at,
                    "updated_at": t.updated_at,
                }
                for t in threads
            ],
            "total": len(threads),
        }
