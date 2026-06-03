"""
对话业务服务层

封装Agent对话相关的业务逻辑，包括：
- 会话管理
- 意图识别
- 回答生成
- 上下文维护
"""

import uuid
from typing import List, Optional

from app.core.logging import get_logger
from app.db.redis import RedisClient, get_redis_client
from app.models.transaction import (
    ChatHistory,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    SourceItem
)

logger = get_logger(__name__)


class ChatService:
    """
    对话业务服务
    
    管理用户对话会话，集成意图识别和回答生成。
    使用Redis存储会话状态。
    """
    
    # 最大历史消息数
    MAX_HISTORY = 20
    
    def __init__(self, redis: Optional[RedisClient] = None):
        self._redis = redis
    
    async def _get_redis(self) -> Optional[RedisClient]:
        """获取Redis客户端（延迟初始化，支持降级）"""
        if not self._redis:
            try:
                self._redis = await get_redis_client()
            except Exception as e:
                logger.warning("Redis连接失败，使用降级模式", error=str(e))
                self._redis = None
        return self._redis
    
    # ========== 会话管理 ==========
    
    async def get_or_create_session(
        self,
        session_id: Optional[str] = None
    ) -> str:
        """
        获取或创建会话
        
        Args:
            session_id: 现有会话ID，None则创建新会话
            
        Returns:
            str: 会话ID
        """
        if session_id:
            # 验证会话是否存在
            redis = await self._get_redis()
            if redis:
                try:
                    exists = await redis.exists(session_id, "session")
                    if exists:
                        return session_id
                except Exception:
                    pass
            logger.warning("会话不存在或Redis不可用，创建新会话", session_id=session_id)
        
        # 创建新会话
        new_session_id = f"sess_{uuid.uuid4().hex[:12]}"
        logger.info("新会话已创建", session_id=new_session_id)
        return new_session_id
    
    async def get_session_history(self, session_id: str) -> ChatHistory:
        """
        获取会话历史
        
        Args:
            session_id: 会话ID
            
        Returns:
            ChatHistory: 会话历史记录
        """
        redis = await self._get_redis()
        if redis:
            try:
                data = await redis.get_session(session_id)
                if data:
                    messages = [
                        ChatMessage(**msg) for msg in data.get("messages", [])
                    ]
                    return ChatHistory(
                        session_id=session_id,
                        messages=messages,
                        created_at=data.get("created_at"),
                        updated_at=data.get("updated_at")
                    )
            except Exception as e:
                logger.warning("Redis读取失败", error=str(e))
        
        return ChatHistory(session_id=session_id, messages=[])
    
    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str
    ) -> None:
        """
        保存消息到会话历史
        
        Args:
            session_id: 会话ID
            role: 消息角色（user/assistant）
            content: 消息内容
        """
        from datetime import datetime
        
        redis = await self._get_redis()
        if not redis:
            logger.debug("Redis不可用，跳过消息保存", session_id=session_id)
            return
        
        try:
            # 获取现有历史
            data = await redis.get_session(session_id) or {
                "messages": [],
                "created_at": datetime.now().isoformat()
            }
            
            # 添加新消息
            data["messages"].append({
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat()
            })
            
            # 限制历史长度
            if len(data["messages"]) > self.MAX_HISTORY:
                data["messages"] = data["messages"][-self.MAX_HISTORY:]
            
            data["updated_at"] = datetime.now().isoformat()
            
            # 保存到Redis
            await redis.set_session(session_id, data)
            logger.debug("消息已保存", session_id=session_id, role=role)
        except Exception as e:
            logger.warning("消息保存失败", error=str(e), session_id=session_id)
    
    # ========== 对话处理 ==========
    
    async def process_chat(self, request: ChatRequest) -> ChatResponse:
        """
        处理对话请求
        
        完整的对话处理流程：
        1. 获取/创建会话
        2. 保存用户消息
        3. 意图识别
        4. 执行查询
        5. 生成回答
        6. 保存助手消息
        
        Args:
            request: 对话请求
            
        Returns:
            ChatResponse: 对话响应
        """
        # 获取会话
        session_id = await self.get_or_create_session(request.session_id)
        
        # 保存用户消息
        await self.save_message(session_id, "user", request.message)
        
        # TODO: 实现完整的Agent流程
        # 1. 意图识别
        # 2. 工具调用
        # 3. 回答生成
        
        # 临时：简单回显
        response_message = f"收到消息：{request.message}"
        
        # 保存助手消息
        await self.save_message(session_id, "assistant", response_message)
        
        return ChatResponse(
            session_id=session_id,
            message=response_message,
            type="answer",
            sources=[],
            suggestions=[]
        )
    
    async def generate_suggestions(
        self,
        query: str,
        context: Optional[dict] = None
    ) -> List[str]:
        """
        生成建议问题
        
        基于当前查询生成相关的后续问题建议。
        
        Args:
            query: 当前查询
            context: 上下文信息
            
        Returns:
            List[str]: 建议问题列表
        """
        # TODO: 基于LLM生成建议
        return [
            "能告诉我更多细节吗？",
            "还有其他相关信息吗？",
            "他们之间的关系如何？"
        ]
    
    # ========== 会话清理 ==========
    
    async def clear_session(self, session_id: str) -> bool:
        """
        清除会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            bool: 清除成功返回True
        """
        redis = await self._get_redis()
        if redis:
            try:
                result = await redis.delete_session(session_id)
                logger.info("会话已清除", session_id=session_id)
                return result > 0
            except Exception as e:
                logger.warning("清除会话失败", error=str(e))
        return False


# 服务实例（单例）
_chat_service: Optional[ChatService] = None


async def get_chat_service() -> ChatService:
    """
    获取对话服务实例（依赖注入用）
    
    Returns:
        ChatService: 对话服务实例
    """
    global _chat_service
    if not _chat_service:
        _chat_service = ChatService()
    return _chat_service
