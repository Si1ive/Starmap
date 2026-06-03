"""
全局错误处理中间件

统一处理API异常，提供：
- 结构化错误响应
- 错误日志记录
- 请求追踪ID传递
- 敏感信息过滤
"""

import traceback
import uuid
from typing import Any, Dict, Optional

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger, set_request_id, clear_request_id
from app.db.neo4j import Neo4jConnectionError, Neo4jQueryError
from app.db.redis import RedisConnectionError
from app.db.chroma import ChromaConnectionError

logger = get_logger(__name__)


class APIException(Exception):
    """
    自定义API异常基类
    
    Attributes:
        status_code: HTTP状态码
        code: 业务错误码
        message: 用户友好的错误信息
        detail: 详细错误信息（仅开发环境显示）
    """
    
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        code: str = "INTERNAL_ERROR",
        detail: Optional[str] = None
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)


class NotFoundException(APIException):
    """资源不存在异常"""
    
    def __init__(self, resource: str = "资源", identifier: str = ""):
        super().__init__(
            message=f"{resource}不存在" + (f": {identifier}" if identifier else ""),
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND"
        )


class ValidationException(APIException):
    """参数验证异常"""
    
    def __init__(self, message: str = "参数验证失败", detail: Optional[str] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            detail=detail
        )


class DatabaseException(APIException):
    """数据库操作异常"""
    
    def __init__(self, message: str = "数据库操作失败"):
        super().__init__(
            message=message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="DATABASE_ERROR"
        )


class LLMException(APIException):
    """LLM调用异常"""
    
    def __init__(self, message: str = "AI服务暂时不可用"):
        super().__init__(
            message=message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="LLM_ERROR"
        )


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    全局错误处理中间件
    
    捕获所有未处理异常，返回统一的错误响应格式。
    同时负责设置请求追踪ID。
    """
    
    async def dispatch(self, request: Request, call_next):
        # 生成请求追踪ID
        request_id = str(uuid.uuid4())
        set_request_id(request_id)
        
        # 记录请求开始
        logger.info(
            "请求开始",
            method=request.method,
            path=request.url.path,
            query=str(request.query_params)
        )
        
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
            
        except APIException as exc:
            # 自定义API异常
            logger.warning(
                "API异常",
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code
            )
            return self._build_error_response(exc, request_id)
            
        except RequestValidationError as exc:
            # 请求参数验证错误
            validation_error = ValidationException(
                message="请求参数验证失败",
                detail=str(exc)
            )
            logger.warning(
                "参数验证失败",
                errors=exc.errors()
            )
            return self._build_error_response(validation_error, request_id)
            
        except (Neo4jConnectionError, Neo4jQueryError) as exc:
            # Neo4j异常
            db_error = DatabaseException(message="图数据库服务暂时不可用")
            logger.error("Neo4j异常", error=str(exc))
            return self._build_error_response(db_error, request_id)
            
        except RedisConnectionError as exc:
            # Redis异常
            db_error = DatabaseException(message="缓存服务暂时不可用")
            logger.error("Redis异常", error=str(exc))
            return self._build_error_response(db_error, request_id)
            
        except ChromaConnectionError as exc:
            # ChromaDB异常
            db_error = DatabaseException(message="向量数据库服务暂时不可用")
            logger.error("ChromaDB异常", error=str(exc))
            return self._build_error_response(db_error, request_id)
            
        except Exception as exc:
            # 未预料的异常
            logger.error(
                "未处理异常",
                error=str(exc),
                traceback=traceback.format_exc()
            )
            internal_error = APIException(
                message="服务器内部错误",
                detail=str(exc) if False else None  # 生产环境不暴露详情
            )
            return self._build_error_response(internal_error, request_id)
            
        finally:
            clear_request_id()
    
    def _build_error_response(
        self,
        exc: APIException,
        request_id: str
    ) -> JSONResponse:
        """
        构建统一错误响应
        
        Args:
            exc: API异常实例
            request_id: 请求追踪ID
            
        Returns:
            JSONResponse: 标准错误响应
        """
        content: Dict[str, Any] = {
            "code": exc.code,
            "message": exc.message,
            "request_id": request_id
        }
        
        # 开发环境显示详细错误
        from app.core.config import settings
        if settings.DEBUG and exc.detail:
            content["detail"] = exc.detail
        
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers={"X-Request-ID": request_id}
        )


# 异常处理器（用于直接注册到FastAPI）
async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
    """API异常处理器"""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "request_id": request_id
        },
        headers={"X-Request-ID": request_id}
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
) -> JSONResponse:
    """验证异常处理器"""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    
    # 提取友好的错误信息
    errors = exc.errors()
    messages = []
    for error in errors:
        loc = " -> ".join(str(x) for x in error.get("loc", []))
        msg = error.get("msg", "")
        messages.append(f"{loc}: {msg}")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": "VALIDATION_ERROR",
            "message": "请求参数验证失败",
            "detail": messages,
            "request_id": request_id
        },
        headers={"X-Request-ID": request_id}
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """通用异常处理器"""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    
    logger.error(
        "未处理异常",
        error=str(exc),
        traceback=traceback.format_exc()
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": "INTERNAL_ERROR",
            "message": "服务器内部错误",
            "request_id": request_id
        },
        headers={"X-Request-ID": request_id}
    )
