"""
API接口测试

测试所有RESTful API端点的功能和响应格式。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.transaction import ChatHistory, ChatResponse
from app.services.chat_service import get_chat_service

client = TestClient(app)


class StubChatService:
    async def process_chat(self, request):
        return ChatResponse(
            session_id=request.session_id or "sess_test_generated",
            message=f"已收到：{request.message}",
            sources=[],
            suggestions=["继续复习"],
        )

    async def get_session_history(self, session_id):
        return ChatHistory(session_id=session_id, messages=[])


@pytest.fixture(autouse=True)
def override_chat_service():
    app.dependency_overrides[get_chat_service] = StubChatService
    yield
    app.dependency_overrides.pop(get_chat_service, None)


class TestHealthAPI:
    """健康检查API测试"""
    
    def test_health_check(self):
        """测试健康检查接口"""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] in ["healthy", "degraded"]
        assert data["version"] == "1.0.0"
        assert "services" in data
        assert "mysql" in data["services"]
        assert "redis" in data["services"]
    
    def test_root_endpoint(self):
        """测试根路径"""
        response = client.get("/")
        assert response.status_code == 200
        
        data = response.json()
        assert "message" in data
        assert "docs" in data
        assert "health" in data


class TestChatAPI:
    """对话API测试"""
    
    def test_chat_message(self):
        """测试发送消息"""
        response = client.post("/api/v1/chat", json={
            "message": "周杰伦的妻子是谁？"
        })
        assert response.status_code == 200
        
        data = response.json()
        assert "session_id" in data
        assert "message" in data
        assert "type" in data
        assert "sources" in data
        assert "suggestions" in data
    
    def test_chat_with_session(self):
        """测试带会话ID的对话"""
        response = client.post("/api/v1/chat", json={
            "message": "你好",
            "session_id": "sess_test_123"
        })
        assert response.status_code == 200
        
        data = response.json()
        # Redis不可用时创建新会话，验证会话ID格式即可
        assert data["session_id"].startswith("sess_")
    
    def test_chat_empty_message(self):
        """测试空消息"""
        response = client.post("/api/v1/chat", json={
            "message": ""
        })
        assert response.status_code == 422  # 验证错误
    
    def test_chat_history(self):
        """测试获取会话历史"""
        response = client.get("/api/v1/chat/sess_test_123/history")
        assert response.status_code == 200
        
        data = response.json()
        assert "session_id" in data
        assert "messages" in data


class TestErrorHandling:
    """错误处理测试"""
    
    def test_request_validation_error(self):
        """测试请求参数验证错误"""
        response = client.post("/api/v1/chat", json={})
        assert response.status_code == 422
        
        data = response.json()
        assert "code" in data
        assert "message" in data
        assert "request_id" in data
    
    def test_not_found_endpoint(self):
        """测试不存在的端点"""
        response = client.get("/api/v1/not-exist")
        assert response.status_code == 404
    
    def test_request_id_header(self):
        """测试响应包含请求追踪ID"""
        response = client.get("/health")
        assert "X-Request-ID" in response.headers


class TestCORS:
    """CORS配置测试"""
    
    def test_cors_headers(self):
        """测试CORS响应头"""
        response = client.options("/health", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET"
        })
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
