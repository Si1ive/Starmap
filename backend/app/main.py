"""
408考研学习平台 API 主入口

FastAPI应用入口，负责：
- 应用初始化
- 中间件注册
- 路由注册
- 生命周期管理
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.redis import redis_client
from app.db.mysql import mysql_client
from app.modules.catalog import router as catalog_router
from app.modules.catalog.chapter_link_router import (
    router as chapter_link_router,
)
from app.modules.catalog.chapter_relation_router import (
    router as chapter_relation_router,
)
from app.modules.catalog.outline_router import router as outline_router
from app.modules.catalog.section_review_router import (
    router as section_review_router,
)
from app.modules.chat.admin_router import router as chat_admin_router
from app.modules.chat.router import router as chat_router
from app.modules.content import router as content_router
from app.modules.content.asset_router import router as asset_router
from app.modules.content.relation_review_router import (
    router as relation_review_router,
)
from app.modules.corpus.router import router as corpus_router
from app.modules.crawler.config_router import router as crawler_config_router
from app.modules.crawler.file_router import router as crawler_file_router
from app.modules.crawler.log_router import router as crawler_log_router
from app.modules.crawler.pdf_ingest_router import router as pdf_ingest_router
from app.modules.crawler.schedule_router import router as crawler_schedule_router
from app.modules.crawler.source_router import router as crawler_source_router
from app.modules.crawler.stats_router import router as crawler_stats_router
from app.modules.crawler.task_router import router as crawler_task_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.monitoring.router import router as monitoring_router
from app.modules.operations import router as operations_router
from app.modules.operations.settings_router import router as settings_router
from app.modules.operations.security import (
    require_current_admin,
    validate_admin_security_config,
)
from app.modules.retrieval.router import router as retrieval_router
from app.modules.operations.schema_guard import (
    DatabaseSchemaError,
    verify_database_schema,
)
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
    """应用生命周期管理"""
    configure_logging()
    validate_admin_security_config()
    logger.info("408考研学习平台 API 启动中...")

    try:
        await redis_client.connect()
        logger.info("Redis连接成功")
    except Exception as e:
        logger.warning("Redis连接失败，服务将在降级模式下运行", error=str(e))

    try:
        await mysql_client.connect()
        logger.info("MySQL连接成功")
    except Exception as e:
        logger.warning("MySQL连接失败，服务将在降级模式下运行", error=str(e))
    else:
        try:
            async with mysql_client.session() as session:
                revisions = await verify_database_schema(session)
            logger.info(
                "数据库结构版本校验通过",
                revisions=sorted(revisions),
            )
        except DatabaseSchemaError as e:
            logger.critical("数据库结构版本校验失败", error=str(e))
            await mysql_client.close()
            raise

    try:
        from app.tasks.scheduler import init_scheduler

        await init_scheduler()
        logger.info("APScheduler调度器初始化成功")
    except Exception as e:
        logger.warning("APScheduler调度器初始化失败", error=str(e))

    try:
        from app.modules.crawler.log_handler import init_log_handler

        await init_log_handler()
        logger.info("日志处理器初始化成功")
    except Exception as e:
        logger.warning("日志处理器初始化失败", error=str(e))

    try:
        from app.modules.crawler.scrapy_bridge import start_scrapy_event_listener

        await start_scrapy_event_listener()
        logger.info("Scrapy事件监听器初始化成功")
    except Exception as e:
        logger.warning("Scrapy事件监听器初始化失败", error=str(e))

    # 启动后台监控相关组件
    try:
        from app.modules.monitoring.log_sink import start_db_log_sink

        await start_db_log_sink()
        logger.info("服务日志 DB sink 启动成功")
    except Exception as e:
        logger.warning("服务日志 DB sink 启动失败", error=str(e))

    try:
        from app.modules.monitoring.system_metrics import start_metrics_collector

        await start_metrics_collector()
        logger.info("系统资源采集器启动成功")
    except Exception as e:
        logger.warning("系统资源采集器启动失败", error=str(e))

    try:
        from app.modules.monitoring.api_stats import start_api_stats_flusher

        await start_api_stats_flusher()
        logger.info("API 统计 flusher 启动成功")
    except Exception as e:
        logger.warning("API 统计 flusher 启动失败", error=str(e))

    logger.info("408考研学习平台 API 启动完成")
    yield

    logger.info("408考研学习平台 API 关闭中...")

    try:
        await redis_client.close()
        logger.info("Redis连接已关闭")
    except Exception as e:
        logger.error("Redis关闭失败", error=str(e))

    try:
        from app.modules.crawler.scrapy_bridge import stop_scrapy_event_listener

        await stop_scrapy_event_listener()
        logger.info("Scrapy事件监听器已关闭")
    except Exception as e:
        logger.error("Scrapy事件监听器关闭失败", error=str(e))

    try:
        from app.modules.monitoring.api_stats import stop_api_stats_flusher

        await stop_api_stats_flusher()
        logger.info("API 统计 flusher 已关闭")
    except Exception as e:
        logger.error("API 统计 flusher 关闭失败", error=str(e))

    try:
        from app.modules.monitoring.system_metrics import stop_metrics_collector

        await stop_metrics_collector()
        logger.info("系统资源采集器已关闭")
    except Exception as e:
        logger.error("系统资源采集器关闭失败", error=str(e))

    try:
        from app.modules.monitoring.log_sink import stop_db_log_sink

        await stop_db_log_sink()
        logger.info("服务日志 DB sink 已关闭")
    except Exception as e:
        logger.error("服务日志 DB sink 关闭失败", error=str(e))

    try:
        await mysql_client.close()
        logger.info("MySQL连接已关闭")
    except Exception as e:
        logger.error("MySQL关闭失败", error=str(e))

    try:
        from app.tasks.scheduler import shutdown_scheduler

        await shutdown_scheduler()
        logger.info("APScheduler调度器已关闭")
    except Exception as e:
        logger.error("APScheduler调度器关闭失败", error=str(e))

    try:
        from app.modules.crawler.log_handler import shutdown_log_handler

        await shutdown_log_handler()
        logger.info("日志处理器已关闭")
    except Exception as e:
        logger.error("日志处理器关闭失败", error=str(e))

    logger.info("408考研学习平台 API 已关闭")


# 创建FastAPI应用
app = FastAPI(
    title="408考研学习平台 API",
    description="408计算机考研结构化学习平台",
    version="1.0.0",
    lifespan=lifespan,
)

# 注册异常处理器
from fastapi.exceptions import RequestValidationError

app.add_exception_handler(APIException, api_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# 注册中间件
app.add_middleware(ErrorHandlerMiddleware)

# API 调用统计中间件（按 endpoint 聚合到 api_call_stats）
from app.modules.monitoring.api_stats import APIStatsMiddleware

app.add_middleware(APIStatsMiddleware)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/api/v1")
admin_dependencies = [Depends(require_current_admin)]
app.include_router(
    chat_admin_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    dashboard_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    settings_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    catalog_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    chapter_link_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    chapter_relation_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    outline_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    section_review_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    content_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    asset_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    relation_review_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    corpus_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    crawler_log_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    crawler_config_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    crawler_task_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    crawler_source_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    crawler_stats_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    crawler_schedule_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    crawler_file_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    pdf_ingest_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    retrieval_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)
app.include_router(
    monitoring_router,
    prefix="/api/v1",
    dependencies=admin_dependencies,
)


@app.get("/health")
async def health_check():
    """健康检查接口"""
    redis_healthy = await redis_client.health_check()
    mysql_healthy = await mysql_client.health_check()

    status = "healthy" if all([redis_healthy, mysql_healthy]) else "degraded"

    return {
        "status": status,
        "version": "1.0.0",
        "services": {
            "mysql": "up" if mysql_healthy else "down",
            "redis": "up" if redis_healthy else "down",
        },
    }


@app.get("/")
async def root():
    return {
        "message": "Welcome to 408考研学习平台 API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }
