"""ChatService 业务逻辑测试。"""

from contextlib import asynccontextmanager

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.mysql import mysql_client
from app.models.mysql_models import ChatMessageRecord, ChatSession
from app.models.transaction import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.services.retrieval_service import RetrievalService
from app.services.system_settings_service import SystemSettingsService


class TestChatService:
    """对话服务测试"""
    
    @pytest.fixture
    def service(self):
        """创建测试服务"""
        return ChatService()
    
    @pytest.mark.asyncio
    async def test_create_new_session(self, service):
        """测试创建新会话"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)
        service._redis = mock_redis
        
        session_id = await service.get_or_create_session()
        
        assert session_id.startswith("sess_")
        assert len(session_id) > 5
    
    @pytest.mark.asyncio
    async def test_use_existing_session(self, service):
        """测试使用现有会话"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=True)
        service._redis = mock_redis
        
        session_id = await service.get_or_create_session("sess_existing")
        
        assert session_id == "sess_existing"
    
    @pytest.mark.asyncio
    async def test_save_and_get_history(self, service):
        """测试保存和获取历史"""
        mock_redis = AsyncMock()
        mock_redis.get_session = AsyncMock(return_value=None)
        mock_redis.set_session = AsyncMock(return_value=True)
        service._redis = mock_redis
        service._persist_message_to_db = AsyncMock()
        
        # 保存消息
        await service.save_message("sess_123", "user", "你好")
        
        # 验证保存调用
        mock_redis.set_session.assert_called_once()
        call_args = mock_redis.set_session.call_args
        assert call_args[0][0] == "sess_123"
        service._persist_message_to_db.assert_awaited_once_with(
            "sess_123",
            "user",
            "你好",
        )

    @pytest.mark.asyncio
    async def test_first_message_flushes_session_before_message(self, service):
        """首次写入时先持久化父会话，避免消息外键失败。"""
        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield db

        with patch.object(mysql_client, "session", fake_session):
            await service._persist_message_to_db("sess_123", "user", "什么是进程？")

        first_entity = db.add.call_args_list[0].args[0]
        second_entity = db.add.call_args_list[1].args[0]
        assert isinstance(first_entity, ChatSession)
        assert isinstance(second_entity, ChatMessageRecord)
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()
    
    @pytest.mark.asyncio
    async def test_process_chat(self, service):
        """测试处理对话"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.get_session = AsyncMock(return_value=None)
        mock_redis.set_session = AsyncMock(return_value=True)
        service._redis = mock_redis
        service.save_message = AsyncMock()
        service._generate_rag_answer = AsyncMock(return_value="进程是程序的一次执行过程。")
        service.generate_suggestions = AsyncMock(return_value=["进程有哪些状态？"])

        @asynccontextmanager
        async def fake_session():
            yield MagicMock()

        retrieval_result = {
            "results": [
                {
                    "content_text": "进程是操作系统进行资源分配和调度的基本单位。",
                    "source": {},
                }
            ],
            "outline_expansion": {"matched_chapters": []},
        }

        with (
            patch.object(mysql_client, "session", fake_session),
            patch.object(SystemSettingsService, "load", AsyncMock(return_value={"llm": {}})),
            patch.object(
                RetrievalService,
                "search_with_outline_expansion",
                AsyncMock(return_value=retrieval_result),
            ),
        ):
            request = ChatRequest(message="什么是进程？")
            response = await service.process_chat(request)
        
        assert isinstance(response, ChatResponse)
        assert response.session_id.startswith("sess_")
        assert response.message == "进程是程序的一次执行过程。"
        assert response.suggestions == ["进程有哪些状态？"]
        assert service.save_message.await_count == 2
    
    @pytest.mark.asyncio
    async def test_clear_session(self, service):
        """测试清除会话"""
        mock_redis = AsyncMock()
        mock_redis.delete_session = AsyncMock(return_value=1)
        service._redis = mock_redis
        
        result = await service.clear_session("sess_123")
        
        assert result is True
        mock_redis.delete_session.assert_called_once_with("sess_123")
