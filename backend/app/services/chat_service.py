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

from app.core.config import settings
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

# RAG 系统提示词
RAG_SYSTEM_PROMPT = """你是一个408计算机考研学习助手。你的任务是基于提供的知识库内容，准确回答用户关于数据结构、计算机组成原理、操作系统、计算机网络的问题。

规则：
1. 只基于提供的知识库内容回答，不要编造信息
2. 如果知识库中没有相关内容，明确告知用户
3. 回答要简洁清晰，适合考研复习
4. 如果涉及算法或公式，用简洁的方式呈现
5. 可以适当举例帮助理解

知识库内容：
{context}"""


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
        处理对话请求（RAG模式）

        流程：
        1. 获取/创建会话
        2. 保存用户消息
        3. 从ChromaDB检索相关知识点
        4. 构建带上下文的prompt
        5. 调用LLM生成回答
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

        # 检索相关知识点
        sources = []
        context_parts = []

        try:
            from app.db.chroma import get_chroma_client
            chroma = get_chroma_client()
            results = chroma.search_knowledge_points(
                query=request.message,
                n_results=5
            )

            for r in results:
                title = r.get("metadata", {}).get("title", "未知")
                content = r.get("document", "")
                # 截取前500字作为上下文
                context_parts.append(f"【{title}】\n{content[:500]}")
                sources.append(SourceItem(
                    type="knowledge_base",
                    title=title,
                    content=content[:200]
                ))
        except Exception as e:
            logger.warning("ChromaDB检索失败，降级为直接回答", error=str(e))

        # 生成回答
        if context_parts:
            # RAG模式：基于知识库回答
            context = "\n\n---\n\n".join(context_parts)
            response_message = await self._generate_rag_answer(
                request.message, context
            )
        else:
            # 降级模式：直接调用LLM
            response_message = await self._generate_direct_answer(
                request.message
            )

        # 生成建议问题
        suggestions = await self.generate_suggestions(
            request.message,
            context={"has_knowledge": bool(context_parts)}
        )

        # 保存助手消息
        await self.save_message(session_id, "assistant", response_message)

        return ChatResponse(
            session_id=session_id,
            message=response_message,
            type="answer",
            sources=sources,
            suggestions=suggestions
        )

    async def _generate_rag_answer(self, question: str, context: str) -> str:
        """基于检索到的知识库内容生成回答"""
        try:
            import openai
            openai.api_key = settings.OPENAI_API_KEY

            messages = [
                {"role": "system", "content": RAG_SYSTEM_PROMPT.format(context=context)},
                {"role": "user", "content": question}
            ]

            response = openai.ChatCompletion.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                max_tokens=1500,
                temperature=0.3
            )

            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error("LLM调用失败", error=str(e))
            # 降级：返回检索到的内容摘要
            if context:
                return f"根据知识库找到以下相关内容：\n\n{context[:1000]}\n\n（注意：AI生成服务暂时不可用，以上为原始知识库内容）"
            return "抱歉，暂时无法回答您的问题。请稍后再试。"

    async def _generate_direct_answer(self, question: str) -> str:
        """直接调用LLM回答（无知识库上下文）"""
        try:
            import openai
            openai.api_key = settings.OPENAI_API_KEY

            messages = [
                {"role": "system", "content": "你是一个408计算机考研学习助手。请简洁准确地回答用户的问题。"},
                {"role": "user", "content": question}
            ]

            response = openai.ChatCompletion.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                max_tokens=1000,
                temperature=0.5
            )

            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error("LLM调用失败", error=str(e))
            return "抱歉，AI服务暂时不可用。请稍后再试。"
    
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
        # 基于408考研场景的建议
        suggestions = [
            "这个知识点常考的题型有哪些？",
            "能举一个具体的例子吗？",
            "和这个知识点相关的其他概念是什么？"
        ]

        # 如果有知识库上下文，生成更具体的建议
        if context and context.get("has_knowledge"):
            try:
                import openai
                openai.api_key = settings.OPENAI_API_KEY

                response = openai.ChatCompletion.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": "基于用户的问题，生成3个相关的后续学习问题。只返回问题列表，每行一个。"},
                        {"role": "user", "content": query}
                    ],
                    max_tokens=200,
                    temperature=0.7
                )

                content = response.choices[0].message.content.strip()
                llm_suggestions = [s.strip() for s in content.split("\n") if s.strip()]
                if len(llm_suggestions) >= 2:
                    return llm_suggestions[:3]
            except Exception:
                pass

        return suggestions
    
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
