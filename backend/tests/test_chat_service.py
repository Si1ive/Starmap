"""ChatService 业务逻辑测试。"""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.mysql import mysql_client
from app.models.mysql_models import ChatMessageRecord, ChatSession
from app.models.transaction import ChatRequest, ChatResponse, SourceItem
from app.modules.retrieval.service import RetrievalService
from app.services.chat_service import ChatService
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
            [],
        )

    @pytest.mark.asyncio
    async def test_save_message_persists_structured_sources(self, service):
        """助手引用应同时写入 Redis 和 MySQL。"""
        mock_redis = AsyncMock()
        mock_redis.get_session = AsyncMock(return_value=None)
        mock_redis.set_session = AsyncMock(return_value=True)
        service._redis = mock_redis
        service._persist_message_to_db = AsyncMock()
        source = SourceItem(
            type="knowledge_point",
            title="进程",
            entity_id="knowledge-1",
            url="/knowledge/knowledge-1",
            score=0.88,
        )

        await service.save_message(
            "sess_123",
            "assistant",
            "进程是程序的一次执行。",
            sources=[source],
        )

        redis_payload = mock_redis.set_session.call_args.args[1]
        assert redis_payload["messages"][0]["sources"][0]["entity_id"] == "knowledge-1"
        persisted_sources = service._persist_message_to_db.await_args.args[3]
        assert persisted_sources[0]["type"] == "knowledge_point"
        assert persisted_sources[0]["score"] == pytest.approx(0.88)

    @pytest.mark.asyncio
    async def test_get_history_falls_back_to_mysql_with_sources(self, service):
        """Redis 缓存缺失时应从 MySQL 恢复消息及其引用。"""
        mock_redis = AsyncMock()
        mock_redis.get_session = AsyncMock(return_value=None)
        service._redis = mock_redis
        now = datetime.now()
        chat_session = SimpleNamespace(created_at=now, updated_at=now)
        record = SimpleNamespace(
            role="assistant",
            content="选择 D。",
            created_at=now,
            citations=[{
                "type": "question",
                "title": "操作系统真题.pdf",
                "entity_id": "question-30",
                "url": "/practice?question_id=question-30",
                "page_no": 12,
            }],
        )
        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = chat_session
        message_result = MagicMock()
        message_result.scalars.return_value.all.return_value = [record]
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[session_result, message_result])

        @asynccontextmanager
        async def fake_session():
            yield db

        with patch.object(mysql_client, "session", fake_session):
            history = await service.get_session_history("sess_123")

        assert history.messages[0].content == "选择 D。"
        assert history.messages[0].sources[0].entity_id == "question-30"
        assert history.messages[0].sources[0].page_no == 12

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
    async def test_process_chat_returns_traceable_question_source(self, service):
        """题目范围检索应返回可追溯引用，而不是在来源模型校验时报错。"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)
        service._redis = mock_redis
        service.save_message = AsyncMock()
        service._generate_rag_answer = AsyncMock(return_value="选择 D。")
        service.generate_suggestions = AsyncMock(return_value=[])

        @asynccontextmanager
        async def fake_session():
            yield MagicMock()

        retrieval_result = {
            "results": [
                {
                    "entity_type": "question",
                    "entity_id": "question-30",
                    "content_text": "第30题：下列关于文件系统的说法正确的是？",
                    "context_text": "第30题及其选项和解析",
                    "score": 0.91,
                    "source": {
                        "document_id": "document-1",
                        "filename": "操作系统真题.pdf",
                        "page_no": 12,
                    },
                }
            ],
            "outline_expansion": {"matched_chapters": []},
        }
        retrieval_mock = AsyncMock(return_value=retrieval_result)

        with (
            patch.object(mysql_client, "session", fake_session),
            patch.object(SystemSettingsService, "load", AsyncMock(return_value={"llm": {}})),
            patch.object(RetrievalService, "search_with_outline_expansion", retrieval_mock),
        ):
            response = await service.process_chat(
                ChatRequest(message="第30题为什么选 D？", retrieval_target="question")
            )

        retrieval_mock.assert_awaited_once()
        assert retrieval_mock.await_args.kwargs["entity_type"] == "question"
        assert response.sources[0].type == "question"
        assert response.sources[0].entity_id == "question-30"
        assert response.sources[0].page_no == 12
        assert response.sources[0].score == pytest.approx(0.91)
        assert response.sources[0].url == "/practice?question_id=question-30"
    
    @pytest.mark.asyncio
    async def test_clear_session(self, service):
        """测试清除会话"""
        mock_redis = AsyncMock()
        mock_redis.delete_session = AsyncMock(return_value=1)
        service._redis = mock_redis
        
        result = await service.clear_session("sess_123")
        
        assert result is True
        mock_redis.delete_session.assert_called_once_with("sess_123")
