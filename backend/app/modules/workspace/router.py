"""
Workspace Router：线程管理 + 产物管理
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.mysql import mysql_client
from app.modules.identity.dependencies import require_current_user
from app.modules.identity.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/workspace", tags=["Workspace"])


async def get_db():
    async with mysql_client.session() as session:
        yield session


async def get_current_user_id(user: User = Depends(require_current_user)) -> str:
    return user.id.hex


@router.get("/threads")
async def list_workspace_threads(
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """列出工作台的线程（Agent Router 已提供，这里作为别名）"""
    from app.modules.agent.service import AgentService
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
