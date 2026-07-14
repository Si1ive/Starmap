"""后台会话管理路由。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.models.mysql_models import ChatMessageRecord, ChatSession

router = APIRouter(prefix="/admin", tags=["后台管理"])


@router.get("/conversations", response_model=ApiResponse)
async def get_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """分页查询会话列表，支持按标题和首条消息搜索。"""
    query = select(ChatSession).order_by(ChatSession.updated_at.desc())
    count_query = select(func.count(ChatSession.id))

    if q:
        like = f"%{q}%"
        condition = or_(
            ChatSession.title.like(like),
            ChatSession.first_message.like(like),
        )
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = (await db.execute(count_query)).scalar_one() or 0
    rows = (
        await db.execute(
            query.offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()

    items = [
        {
            "id": session.id,
            "title": session.title,
            "first_message": session.first_message,
            "last_message": session.last_message,
            "message_count": int(session.message_count or 0),
            "has_knowledge": bool(session.has_knowledge),
            "created_at": (
                session.created_at.isoformat() + "Z"
                if session.created_at
                else None
            ),
            "updated_at": (
                session.updated_at.isoformat() + "Z"
                if session.updated_at
                else None
            ),
        }
        for session in rows
    ]

    return ApiResponse(
        data={
            "items": items,
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "total_pages": (
                (int(total) + page_size - 1) // page_size if total else 0
            ),
        }
    )


@router.get("/conversations/{conversation_id}", response_model=ApiResponse)
async def get_conversation_detail(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取会话基本信息和完整消息列表。"""
    chat_session = (
        await db.execute(
            select(ChatSession).where(ChatSession.id == conversation_id)
        )
    ).scalar_one_or_none()
    if not chat_session:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = (
        await db.execute(
            select(ChatMessageRecord)
            .where(ChatMessageRecord.session_id == conversation_id)
            .order_by(ChatMessageRecord.id)
        )
    ).scalars().all()

    return ApiResponse(
        data={
            "id": chat_session.id,
            "title": chat_session.title,
            "first_message": chat_session.first_message,
            "last_message": chat_session.last_message,
            "message_count": int(chat_session.message_count or 0),
            "has_knowledge": bool(chat_session.has_knowledge),
            "metadata_json": chat_session.metadata_json,
            "created_at": (
                chat_session.created_at.isoformat() + "Z"
                if chat_session.created_at
                else None
            ),
            "updated_at": (
                chat_session.updated_at.isoformat() + "Z"
                if chat_session.updated_at
                else None
            ),
            "messages": [
                {
                    "id": str(message.id),
                    "role": message.role,
                    "content": message.content,
                    "citations": message.citations or [],
                    "llm_call_id": message.llm_call_id,
                    "timestamp": (
                        message.created_at.isoformat() + "Z"
                        if message.created_at
                        else None
                    ),
                }
                for message in messages
            ],
        }
    )


@router.delete("/conversations/{conversation_id}", response_model=ApiResponse)
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除会话及其所有消息。"""
    result = await db.execute(
        delete(ChatSession).where(ChatSession.id == conversation_id)
    )
    await db.commit()
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="会话不存在")
    return ApiResponse(data={"deleted": int(result.rowcount or 0)})
