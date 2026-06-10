"""
业务服务层测试

测试PersonService和ChatService的业务逻辑。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.person import Person, PersonSearchResult, PersonRelationGraph
from app.models.transaction import ChatRequest, ChatResponse
from app.services.person_service import PersonService
from app.services.chat_service import ChatService


class TestPersonService:
    """人物服务测试"""
    
    @pytest.fixture
    def service(self):
        """创建测试服务"""
        return PersonService()
    
    @pytest.fixture
    def mock_person(self):
        """创建测试人物数据"""
        return Person(
            id="jay-chou",
            name="周杰伦",
            category="singer",
            description="华语流行乐男歌手",
            nationality="中国台湾",
            birth_date="1979-01-18"
        )
    
    @pytest.mark.asyncio
    async def test_get_person_from_cache(self, service, mock_person):
        """测试从缓存获取人物"""
        mock_redis = AsyncMock()
        mock_redis.get_json = AsyncMock(return_value=mock_person.model_dump())
        service._redis = mock_redis
        
        result = await service.get_person_by_id("jay-chou")
        
        assert result is not None
        assert result.name == "周杰伦"
        mock_redis.get_json.assert_called_once_with("jay-chou", "person")
    
    @pytest.mark.asyncio
    async def test_get_person_from_db(self, service, mock_person):
        """测试从数据库获取人物"""
        mock_redis = AsyncMock()
        mock_redis.get_json = AsyncMock(return_value=None)
        mock_redis.set_json = AsyncMock(return_value=True)
        
        mock_db = AsyncMock()
        mock_db.get_person_by_id = AsyncMock(return_value=mock_person.model_dump())

        service._redis = mock_redis
        service._db = mock_db

        result = await service.get_person_by_id("jay-chou")

        assert result is not None
        assert result.name == "周杰伦"
        mock_db.get_person_by_id.assert_called_once_with("jay-chou")
        mock_redis.set_json.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_person_not_found(self, service):
        """测试人物不存在"""
        mock_redis = AsyncMock()
        mock_redis.get_json = AsyncMock(return_value=None)
        
        mock_db = AsyncMock()
        mock_db.get_person_by_id = AsyncMock(return_value=None)

        service._redis = mock_redis
        service._db = mock_db
        
        result = await service.get_person_by_id("not-exist")
        
        # 降级模式下返回Mock数据
        assert result is not None
        assert result.id == "not-exist"
    
    @pytest.mark.asyncio
    async def test_search_persons_with_cache(self, service):
        """测试搜索使用缓存"""
        cached_result = {
            "items": [{"id": "jay", "name": "周杰伦", "category": "singer"}],
            "total": 1,
            "page": 1,
            "page_size": 20,
            "total_pages": 1
        }
        
        mock_redis = AsyncMock()
        mock_redis.get_json = AsyncMock(return_value=cached_result)
        service._redis = mock_redis
        
        result = await service.search_persons("周杰伦")
        
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].name == "周杰伦"
    
    @pytest.mark.asyncio
    async def test_search_persons_from_db(self, service):
        """测试搜索从数据库获取"""
        mock_redis = AsyncMock()
        mock_redis.get_json = AsyncMock(return_value=None)
        mock_redis.set_json = AsyncMock(return_value=True)
        
        mock_db = AsyncMock()
        mock_db.search_persons = AsyncMock(return_value=[
            {"id": "jay", "name": "周杰伦", "category": "singer", "avatar_url": None, "description": None}
        ])

        service._redis = mock_redis
        service._db = mock_db

        result = await service.search_persons("周杰伦")

        assert len(result.items) == 1
        mock_db.search_persons.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_person_relations(self, service):
        """测试获取人物关系"""
        mock_redis = AsyncMock()
        mock_redis.get_json = AsyncMock(return_value=None)
        mock_redis.set_json = AsyncMock(return_value=True)
        
        mock_db = AsyncMock()
        mock_db.get_person_relations = AsyncMock(return_value={
            "center": {"id": "jay-chou", "name": "周杰伦"},
            "nodes": [
                {"id": "jay-chou", "name": "周杰伦", "category": "singer"},
                {"id": "hannah", "name": "昆凌", "category": "model"}
            ],
            "edges": [
                {"source": "jay-chou", "target": "hannah", "type": "spouse", "properties": {}}
            ]
        })

        service._redis = mock_redis
        service._db = mock_db
        
        result = await service.get_person_relations("jay-chou", depth=1)
        
        assert result.center.id == "jay-chou"
        assert len(result.nodes) == 2
        assert len(result.edges) == 1
    
    @pytest.mark.asyncio
    async def test_invalidate_person_cache(self, service):
        """测试清除人物缓存"""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=1)
        mock_redis.delete_pattern = AsyncMock(return_value=5)
        service._redis = mock_redis
        
        await service.invalidate_person_cache("jay-chou")
        
        mock_redis.delete.assert_called_once_with("jay-chou", "person")


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
        
        # 保存消息
        await service.save_message("sess_123", "user", "你好")
        
        # 验证保存调用
        mock_redis.set_session.assert_called_once()
        call_args = mock_redis.set_session.call_args
        assert call_args[0][0] == "sess_123"
    
    @pytest.mark.asyncio
    async def test_process_chat(self, service):
        """测试处理对话"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.get_session = AsyncMock(return_value=None)
        mock_redis.set_session = AsyncMock(return_value=True)
        service._redis = mock_redis
        
        request = ChatRequest(message="周杰伦的妻子是谁？")
        response = await service.process_chat(request)
        
        assert isinstance(response, ChatResponse)
        assert response.session_id.startswith("sess_")
        assert "周杰伦的妻子是谁？" in response.message
    
    @pytest.mark.asyncio
    async def test_clear_session(self, service):
        """测试清除会话"""
        mock_redis = AsyncMock()
        mock_redis.delete_session = AsyncMock(return_value=1)
        service._redis = mock_redis
        
        result = await service.clear_session("sess_123")
        
        assert result is True
        mock_redis.delete_session.assert_called_once_with("sess_123")
