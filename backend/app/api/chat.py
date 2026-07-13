"""
对话API路由

提供Agent对话相关的RESTful API：
- POST /chat - 发送消息
- GET /chat/{session_id}/history - 获取历史
"""

from fastapi import APIRouter, Depends

from app.models.transaction import ChatRequest, ChatResponse, ChatHistory
from app.services.chat_service import ChatService, get_chat_service

router = APIRouter(tags=["对话"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service)
):
    """
    与Agent对话
    
    发送消息给AI助手，支持多轮对话。
    首次对话可不传 session_id，系统会自动创建新会话。
    
    - **message**: 用户消息（必填，1-2000字符）
    - **session_id**: 会话ID（可选，首次为空）
    - **context**: 额外上下文（可选）
    - **subject_id**: 限定检索学科（可选）
    - **retrieval_target**: mixed / knowledge / question，默认 mixed
    
    **响应**: 包含AI回复、信息来源和建议问题
    """
    return await service.process_chat(request)


@router.get("/chat/{session_id}/history", response_model=ChatHistory)
async def get_chat_history(
    session_id: str,
    service: ChatService = Depends(get_chat_service)
):
    """
    获取会话历史
    
    返回指定会话的完整对话记录。
    
    - **session_id**: 会话ID
    """
    return await service.get_session_history(session_id)
