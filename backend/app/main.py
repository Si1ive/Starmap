"""
StarMap API 主入口

FastAPI应用入口，负责：
- 应用初始化
- 中间件注册
- 路由注册
- 生命周期管理
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import query, chat, person, recommend, admin
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.neo4j import neo4j_client
from app.db.redis import redis_client
from app.db.chroma import chroma_client
from app.db.mysql import mysql_client
from app.middleware.error_handler import (
    ErrorHandlerMiddleware,
    api_exception_handler,
    validation_exception_handler,
    general_exception_handler,
    APIException,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    
    启动时初始化数据库连接，关闭时释放资源。
    """
    # 启动
    configure_logging()
    logger.info("StarMap API 启动中...", version="1.0.0")
    
    # 初始化数据库连接
    try:
        await neo4j_client.connect()
        logger.info("Neo4j连接成功")
    except Exception as e:
        logger.warning("Neo4j连接失败，服务将在降级模式下运行", error=str(e))
    
    try:
        await redis_client.connect()
        logger.info("Redis连接成功")
    except Exception as e:
        logger.warning("Redis连接失败，服务将在降级模式下运行", error=str(e))
    
    try:
        chroma_client.connect()
        logger.info("ChromaDB连接成功")
    except Exception as e:
        logger.warning("ChromaDB连接失败，服务将在降级模式下运行", error=str(e))
    
    # 初始化 MySQL 连接
    try:
        await mysql_client.connect()
        logger.info("MySQL连接成功")
        
        # 执行数据库迁移
        try:
            from app.tasks.migrate import run_migrations
            await run_migrations()
            logger.info("数据库迁移完成")
        except Exception as e:
            logger.warning("数据库迁移失败", error=str(e))
    except Exception as e:
        logger.warning("MySQL连接失败，服务将在降级模式下运行", error=str(e))
    
    # 初始化 APScheduler 调度器
    try:
        from app.tasks.scheduler import init_scheduler
        scheduler = await init_scheduler()
        logger.info("APScheduler调度器初始化成功")
    except Exception as e:
        logger.warning("APScheduler调度器初始化失败", error=str(e))
    
    # 初始化日志处理器
    try:
        from app.services.log_handler import init_log_handler
        await init_log_handler()
        logger.info("日志处理器初始化成功")
    except Exception as e:
        logger.warning("日志处理器初始化失败", error=str(e))

    # 初始化 Scrapy 事件监听器
    try:
        from app.services.scrapy_bridge import start_scrapy_event_listener
        await start_scrapy_event_listener()
        logger.info("Scrapy事件监听器初始化成功")
    except Exception as e:
        logger.warning("Scrapy事件监听器初始化失败", error=str(e))
    
    logger.info("StarMap API 启动完成")
    yield
    
    # 关闭
    logger.info("StarMap API 关闭中...")
    
    try:
        await neo4j_client.close()
        logger.info("Neo4j连接已关闭")
    except Exception as e:
        logger.error("Neo4j关闭失败", error=str(e))
    
    try:
        await redis_client.close()
        logger.info("Redis连接已关闭")
    except Exception as e:
        logger.error("Redis关闭失败", error=str(e))
    
    try:
        chroma_client.close()
        logger.info("ChromaDB连接已关闭")
    except Exception as e:
        logger.error("ChromaDB关闭失败", error=str(e))
    
    # 关闭 MySQL 连接
    try:
        from app.services.scrapy_bridge import stop_scrapy_event_listener
        await stop_scrapy_event_listener()
        logger.info("Scrapy事件监听器已关闭")
    except Exception as e:
        logger.error("Scrapy事件监听器关闭失败", error=str(e))

    # 关闭 MySQL 连接
    try:
        await mysql_client.close()
        logger.info("MySQL连接已关闭")
    except Exception as e:
        logger.error("MySQL关闭失败", error=str(e))
    
    # 关闭 APScheduler 调度器
    try:
        from app.tasks.scheduler import shutdown_scheduler
        await shutdown_scheduler()
        logger.info("APScheduler调度器已关闭")
    except Exception as e:
        logger.error("APScheduler调度器关闭失败", error=str(e))
    
    # 关闭日志处理器
    try:
        from app.services.log_handler import shutdown_log_handler
        await shutdown_log_handler()
        logger.info("日志处理器已关闭")
    except Exception as e:
        logger.error("日志处理器关闭失败", error=str(e))
    
    logger.info("StarMap API 已关闭")


# 创建FastAPI应用
app = FastAPI(
    title="StarMap API",
    description="艺人知识图谱与对话Agent",
    version="1.0.0",
    lifespan=lifespan
)

# 注册异常处理器
from fastapi.exceptions import RequestValidationError
app.add_exception_handler(APIException, api_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# 注册中间件（注意顺序：错误处理在最外层）
app.add_middleware(ErrorHandlerMiddleware)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 注册路由
app.include_router(query.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(person.router, prefix="/api/v1")
app.include_router(recommend.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    """
    健康检查接口
    
    返回服务状态和数据库连接状态。
    """
    # 检查各组件状态
    neo4j_healthy = await neo4j_client.health_check()
    redis_healthy = await redis_client.health_check()
    chroma_healthy = chroma_client.health_check()
    mysql_healthy = await mysql_client.health_check()
    
    status = "healthy" if all([neo4j_healthy, redis_healthy, chroma_healthy, mysql_healthy]) else "degraded"
    
    return {
        "status": status,
        "version": "1.0.0",
        "services": {
            "mysql": "up" if mysql_healthy else "down",
            "neo4j": "up" if neo4j_healthy else "down",
            "redis": "up" if redis_healthy else "down",
            "chromadb": "up" if chroma_healthy else "down"
        }
    }


@app.get("/")
async def root():
    """
    根路径
    
    返回API基本信息和文档链接。
    """
    return {
        "message": "Welcome to StarMap API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }
