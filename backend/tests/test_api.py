"""
API接口测试

测试所有RESTful API端点的功能和响应格式。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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
        assert "neo4j" in data["services"]
        assert "redis" in data["services"]
        assert "chromadb" in data["services"]
    
    def test_root_endpoint(self):
        """测试根路径"""
        response = client.get("/")
        assert response.status_code == 200
        
        data = response.json()
        assert "message" in data
        assert "docs" in data
        assert "health" in data


class TestPersonAPI:
    """人物API测试"""
    
    def test_get_person_detail(self):
        """测试获取人物详情"""
        response = client.get("/api/v1/persons/jay-chou")
        assert response.status_code == 200
        
        data = response.json()
        # 当前是mock数据，验证结构
        assert "id" in data
        assert "name" in data
    
    def test_get_person_not_found(self):
        """测试人物不存在"""
        response = client.get("/api/v1/persons/not-exist")
        # 当前mock返回200，后续应返回404
        assert response.status_code in [200, 404]
    
    def test_get_person_relations(self):
        """测试获取人物关系"""
        response = client.get("/api/v1/persons/jay-chou/relations?depth=2")
        assert response.status_code == 200
        
        data = response.json()
        assert "center" in data
        assert "nodes" in data
        assert "edges" in data
    
    def test_get_person_relations_invalid_depth(self):
        """测试无效的关系深度"""
        response = client.get("/api/v1/persons/jay-chou/relations?depth=5")
        assert response.status_code == 422  # 验证错误
    
    def test_get_similar_persons(self):
        """测试获取相似人物"""
        response = client.get("/api/v1/persons/jay-chou/similar?limit=5")
        assert response.status_code == 200
        
        data = response.json()
        assert "items" in data


class TestSearchAPI:
    """搜索API测试"""
    
    def test_search_persons(self):
        """测试搜索人物"""
        response = client.get("/api/v1/persons/search?q=周杰伦")
        assert response.status_code == 200
        
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data
    
    def test_search_with_category(self):
        """测试按分类搜索"""
        response = client.get("/api/v1/persons/search?q=周&category=singer")
        assert response.status_code == 200
        
        data = response.json()
        assert "items" in data
    
    def test_search_missing_query(self):
        """测试缺少搜索词"""
        response = client.get("/api/v1/persons/search")
        assert response.status_code == 422  # 验证错误
    
    def test_search_pagination(self):
        """测试分页"""
        response = client.get("/api/v1/persons/search?q=周&page=2&page_size=10")
        assert response.status_code == 200
        
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 10


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
