"""
爬虫任务执行服务

提供爬虫任务的创建、执行、状态管理等核心功能。
通过 Scrapy Bridge 发布实际爬取任务。
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.crawler.cleanup_service import CrawlerCleanupService
from app.modules.crawler.log_service import CrawlerLogService
from app.modules.crawler.scrapy_bridge import ScrapyBridgeService
from app.modules.crawler.source_service import CrawlerSourceService
from app.modules.crawler.task_config import (
    SPIDER_SOURCES,
    TASK_TYPES,
    is_supported_source,
    normalize_keywords,
    normalize_source_ids,
    normalize_task_config,
    source_code_candidates,
    validate_crawl_config,
)
from app.models.mysql_models import CrawlTask, CrawlLog, CrawlSource

logger = get_logger(__name__)


class CrawlerTaskService:
    """爬虫任务执行服务"""

    TASK_TYPES = TASK_TYPES
    SPIDER_SOURCES = SPIDER_SOURCES

    def __init__(self, db: AsyncSession):
        self.db = db
        self.log_service = CrawlerLogService(db)

    async def create_task(
        self,
        name: str,
        task_type: str,
        source_ids: List[str],
        target_config: Optional[Dict[str, Any]] = None,
        created_by: Optional[str] = None,
    ) -> CrawlTask:
        """
        创建爬虫任务
        
        Args:
            name: 任务名称
            task_type: 任务类型 (full/incremental/targeted/health_check/cleanup)
            source_ids: 关联的爬取源ID列表
            target_config: 目标配置
            created_by: 创建者ID
            
        Returns:
            创建的 CrawlTask 实例
        """
        config = self.normalize_task_config(task_type, target_config)

        source_ids = self._normalize_source_ids(source_ids or config.get("source_ids") or [])
        keywords = self._normalize_keywords(config.get("keywords") or config.get("targets") or [])
        config["keywords"] = keywords

        source_service = CrawlerSourceService(self.db)
        await source_service.ensure_default_sources()

        source = None
        if source_ids:
            result = await self.db.execute(
                select(CrawlSource).where(CrawlSource.id == source_ids[0])
            )
            source = result.scalar_one_or_none()
        if not source and config.get("source"):
            result = await self.db.execute(
                select(CrawlSource)
                .where(CrawlSource.code.in_(self._source_code_candidates(config["source"])))
                .limit(1)
            )
            source = result.scalar_one_or_none()
            if source:
                source_ids = [source.id]

        if not source and task_type in {"full", "incremental", "targeted"}:
            compatible_source_codes = self.SPIDER_SOURCES[config["spider_type"]]
            result = await self.db.execute(
                select(CrawlSource)
                .where(
                    CrawlSource.status == "active",
                    CrawlSource.code.in_(compatible_source_codes),
                )
                .order_by(CrawlSource.code)
                .limit(1)
            )
            source = result.scalar_one_or_none()
            if source:
                source_ids = [source.id]

        if task_type in {"full", "incremental", "targeted"}:
            if not source:
                raise ValueError("请选择有效的数据源")
            spider_type = config["spider_type"]
            if not self._is_supported_source(spider_type, source.code):
                raise ValueError(f"{spider_type} 爬虫暂不支持数据源 {source.name}")

        if source:
            config["source"] = source.code
            config["source_ids"] = source_ids

        target_count = len(keywords) or len(source_ids) or None

        task = CrawlTask(
            id=f"task_{uuid.uuid4().hex[:8]}",
            name=name,
            task_type=task_type,
            source=source.code if source else config.get("source"),
            source_id=source_ids[0] if source_ids else None,
            target_count=target_count,
            config=config,
            status="pending",
            progress=0,
            created_by=created_by,
        )
        
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        
        logger.info(f"Created crawl task: {task.name} ({task.id})")
        return task

    @staticmethod
    def _source_code_candidates(source_code: str) -> List[str]:
        """Return database source code candidates for a Scrapy source key."""
        return source_code_candidates(source_code)

    @staticmethod
    def _normalize_source_ids(source_ids: Any) -> List[str]:
        """Normalize source_ids input into a list."""
        return normalize_source_ids(source_ids)

    @staticmethod
    def _normalize_keywords(keywords: Any) -> List[str]:
        """Normalize keyword input into a list."""
        return normalize_keywords(keywords)

    @classmethod
    def normalize_task_config(
        cls,
        task_type: str,
        target_config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Validate and normalize configuration shared by manual and scheduled tasks."""
        return normalize_task_config(
            task_type,
            target_config,
            task_types=cls.TASK_TYPES,
            spider_sources=cls.SPIDER_SOURCES,
        )

    @classmethod
    def _validate_crawl_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate supported spider inputs before persisting a task."""
        return validate_crawl_config(
            config,
            spider_sources=cls.SPIDER_SOURCES,
        )

    @staticmethod
    def _is_supported_source(spider_type: str, source_code: str) -> bool:
        """Check whether a Scrapy spider supports the selected source."""
        return is_supported_source(
            spider_type,
            source_code,
            spider_sources=CrawlerTaskService.SPIDER_SOURCES,
        )

    async def create_task_from_schedule(
        self,
        schedule_id: str,
        schedule_name: str,
        task_type: str,
        source_ids: List[str],
        target_config: Optional[Dict[str, Any]] = None,
    ) -> CrawlTask:
        """
        根据定时任务配置创建爬虫任务
        
        Args:
            schedule_id: 定时任务ID
            schedule_name: 定时任务名称
            task_type: 任务类型
            source_ids: 关联的爬取源ID列表
            target_config: 目标配置
            
        Returns:
            创建的 CrawlTask 实例
        """
        task = await self.create_task(
            name=f"{schedule_name} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
            task_type=task_type,
            source_ids=source_ids,
            target_config=target_config,
            created_by="scheduler",
        )
        
        # 关联到定时任务（通过 config 字段存储 schedule_id）
        if task.config is None:
            task.config = {}
        task.config["schedule_id"] = schedule_id
        await self.db.commit()
        
        return task

    async def execute_task(self, task_id: str) -> CrawlTask:
        """
        执行爬虫任务
        
        将任务发布到 Scrapy 服务 via Redis，由 Scrapy 执行实际爬取。
        
        Args:
            task_id: 任务ID
            
        Returns:
            执行后的 CrawlTask 实例
        """
        task = await self.get_task_by_id(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        
        if task.status == "running":
            raise ValueError(f"Task already running: {task_id}")
        
        # 更新状态为运行中
        task.status = "running"
        task.started_at = datetime.utcnow()
        await self.db.commit()
        
        logger.info(f"Starting crawl task via Scrapy: {task.name} ({task.id})")
        
        try:
            if task.task_type in ("health_check", "cleanup"):
                if task.task_type == "health_check":
                    await self._execute_health_check(task)
                else:
                    await self._execute_cleanup(task)

                task.status = "completed"
                task.progress = 100
                task.completed_at = datetime.utcnow()
                await self.db.commit()
                await self.log_service.create_log({
                    "task_id": task_id,
                    "level": "INFO",
                    "stage": "execution",
                    "status": "success",
                    "message": f"Task completed: {task.task_type}",
                })
                await self.db.refresh(task)
                return task

            bridge = ScrapyBridgeService(self.db)
            
            published = await bridge.publish_task(task)
            
            if not published:
                raise RuntimeError("Failed to publish task to Scrapy")
            
            logger.info(f"Task published to Scrapy queue: {task.id}")
            
        except Exception as e:
            # 任务失败
            task.status = "failed"
            task.error_message = str(e)[:500]
            task.completed_at = datetime.utcnow()
            
            logger.error(f"Crawl task failed: {task.name} ({task.id}), error: {e}")
            
            # 记录错误日志
            await self.log_service.create_log({
                "task_id": task_id,
                "level": "ERROR",
                "stage": "execution",
                "status": "failed",
                "message": f"Task execution failed: {str(e)}",
            })
            
            await self.db.commit()
        
        await self.db.refresh(task)
        
        return task

    async def stop_task(self, task_id: str) -> Optional[CrawlTask]:
        """
        停止爬虫任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            停止后的 CrawlTask 实例，如果不存在返回 None
        """
        task = await self.get_task_by_id(task_id)
        if not task:
            return None
        
        if task.status != "running":
            logger.warning(f"Task is not running, cannot stop: {task_id}")
            return task
        
        task.status = "stopped"
        task.completed_at = datetime.utcnow()
        await self.db.commit()
        
        logger.info(f"Stopped crawl task: {task.name} ({task.id})")
        
        # 记录停止日志
        await self.log_service.create_log({
            "task_id": task_id,
            "level": "WARNING",
            "stage": "execution",
            "status": "failed",
            "message": "Task was manually stopped",
        })
        
        return task

    async def get_task_by_id(self, task_id: str) -> Optional[CrawlTask]:
        """根据ID获取任务"""
        result = await self.db.execute(
            select(CrawlTask).where(CrawlTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def delete_task(self, task_id: str) -> bool:
        """删除非运行中的爬虫任务及其日志"""
        task = await self.get_task_by_id(task_id)
        if not task:
            return False
        if task.status == "running":
            raise ValueError("Running task cannot be deleted")

        await self.db.execute(
            CrawlLog.__table__.delete().where(CrawlLog.task_id == task_id)
        )
        await self.db.delete(task)
        await self.db.commit()
        logger.info(f"Deleted crawl task: {task_id}")
        return True

    async def get_tasks(
        self,
        skip: int = 0,
        limit: int = 20,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> tuple[List[CrawlTask], int]:
        """
        获取任务列表
        
        Args:
            skip: 跳过数量
            limit: 限制数量
            status: 状态筛选
            task_type: 任务类型筛选
            source_id: 爬取源筛选
            
        Returns:
            (任务列表, 总数)
        """
        query = select(CrawlTask)
        
        if status:
            query = query.where(CrawlTask.status == status)
        if task_type:
            query = query.where(CrawlTask.task_type == task_type)
        if source_id:
            query = query.where(CrawlTask.source_id == source_id)
        
        # 统计总数
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0
        
        # 分页查询
        query = query.offset(skip).limit(limit).order_by(CrawlTask.created_at.desc())
        result = await self.db.execute(query)
        tasks = result.scalars().all()
        
        return list(tasks), total

    async def update_task_progress(
        self,
        task_id: str,
        progress: int,
        total_requests: Optional[int] = None,
        success_count: Optional[int] = None,
        failed_count: Optional[int] = None,
    ) -> Optional[CrawlTask]:
        """
        更新任务进度
        
        Args:
            task_id: 任务ID
            progress: 进度百分比 (0-100)
            total_requests: 总请求数
            success_count: 成功数
            failed_count: 失败数
            
        Returns:
            更新后的 CrawlTask 实例
        """
        task = await self.get_task_by_id(task_id)
        if not task:
            return None
        
        task.progress = min(max(progress, 0), 100)
        
        if total_requests is not None:
            task.total_requests = total_requests
        if success_count is not None:
            task.success_count = success_count
        if failed_count is not None:
            task.failed_count = failed_count
        
        await self.db.commit()
        
        return task

    # ========== 私有方法：任务执行逻辑 ==========

    async def _execute_health_check(self, task: CrawlTask) -> None:
        """执行健康检查任务"""
        logger.info(f"Executing health check task: {task.id}")
        
        source_service = CrawlerSourceService(self.db)
        
        # 从 config 中获取 source_ids
        source_ids = []
        if task.config and isinstance(task.config, dict):
            source_ids = task.config.get("source_ids", [])
        elif task.source_id:
            source_ids = [task.source_id]
        
        for source_id in source_ids:
            try:
                result = await source_service.health_check(source_id)
                logger.info(f"Health check result for {source_id}: {result['status']}")
            except Exception as e:
                logger.error(f"Health check failed for {source_id}: {e}")

    async def _execute_cleanup(self, task: CrawlTask) -> None:
        """执行爬虫运维数据清理任务。"""
        logger.info(f"Executing cleanup task: {task.id}")

        config = task.config or {}
        await self.update_task_progress(task.id, 10)
        result = await CrawlerCleanupService(self.db).run(
            cleanup_types=config.get("cleanup_types"),
            retention_days=config.get("retention_days", 90),
        )

        total_cleaned = result["total_cleaned"]
        task.target_count = total_cleaned
        task.completed_count = total_cleaned
        await self.update_task_progress(
            task.id,
            100,
            total_requests=total_cleaned,
            success_count=total_cleaned,
            failed_count=0,
        )

        await self.log_service.create_log({
            "task_id": task.id,
            "level": "INFO",
            "stage": "cleanup",
            "status": "success",
            "message": f"Cleanup completed: {total_cleaned} records cleaned",
            "details": result,
        })

        logger.info(f"Cleanup task completed: {task.id}, total_cleaned={total_cleaned}")
