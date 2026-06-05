"""
爬虫任务执行服务

提供爬虫任务的创建、执行、状态管理等核心功能。
集成 BaseCrawler 实现实际爬取逻辑。
"""

import uuid
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CrawlTask, CrawlLog, CrawlSource
from app.services.log_service import CrawlerLogService
from app.services.source_service import CrawlerSourceService

logger = get_logger(__name__)


class CrawlerTaskService:
    """爬虫任务执行服务"""

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
        task = CrawlTask(
            id=f"task_{uuid.uuid4().hex[:8]}",
            name=name,
            task_type=task_type,
            source=source_ids[0] if source_ids else None,
            source_id=source_ids[0] if source_ids else None,
            config=target_config or {},
            status="pending",
            progress=0,
            total_requests=0,
            success_count=0,
            failed_count=0,
            created_by=created_by,
        )
        
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        
        logger.info(f"Created crawl task: {task.name} ({task.id})")
        return task

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
        
        根据任务类型和配置，执行实际的爬取逻辑。
        
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
        
        logger.info(f"Starting crawl task: {task.name} ({task.id})")
        
        try:
            # 根据任务类型执行不同的逻辑
            if task.task_type == "full":
                await self._execute_full_update(task)
            elif task.task_type == "incremental":
                await self._execute_incremental_update(task)
            elif task.task_type == "targeted":
                await self._execute_targeted_crawl(task)
            elif task.task_type == "health_check":
                await self._execute_health_check(task)
            elif task.task_type == "cleanup":
                await self._execute_cleanup(task)
            else:
                raise ValueError(f"Unknown task type: {task.task_type}")
            
            # 任务完成
            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.utcnow()
            
            logger.info(f"Crawl task completed: {task.name} ({task.id})")
            
        except Exception as e:
            # 任务失败
            task.status = "failed"
            task.error_message = str(e)[:500]
            task.completed_at = datetime.utcnow()
            
            logger.error(f"Crawl task failed: {task.name} ({task.id}), error: {e}")
            
            # 记录错误日志
            await self.log_service.create_log({
                "task_id": task_id,
                "level": "error",
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
            "level": "warning",
            "stage": "execution",
            "status": "stopped",
            "message": "Task was manually stopped",
        })
        
        return task

    async def get_task_by_id(self, task_id: str) -> Optional[CrawlTask]:
        """根据ID获取任务"""
        result = await self.db.execute(
            select(CrawlTask).where(CrawlTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_tasks(
        self,
        skip: int = 0,
        limit: int = 20,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
    ) -> tuple[List[CrawlTask], int]:
        """
        获取任务列表
        
        Args:
            skip: 跳过数量
            limit: 限制数量
            status: 状态筛选
            task_type: 任务类型筛选
            
        Returns:
            (任务列表, 总数)
        """
        query = select(CrawlTask)
        
        if status:
            query = query.where(CrawlTask.status == status)
        if task_type:
            query = query.where(CrawlTask.task_type == task_type)
        
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

    async def _execute_full_update(self, task: CrawlTask) -> None:
        """执行全量更新任务"""
        logger.info(f"Executing full update task: {task.id}")
        
        # 获取任务配置
        config = task.config or {}
        source_ids = config.get("source_ids", [])
        keywords = config.get("keywords", [])
        spider_type = config.get("spider_type", "person")
        
        if not keywords:
            logger.warning(f"No keywords provided for task: {task.id}")
            return
        
        # 创建爬虫引擎
        from crawler.engine import CrawlerEngine, Scheduler, Downloader
        from crawler.pipelines import (
            DataCleaningPipeline,
            DataValidationPipeline,
            DatabaseStoragePipeline,
            Neo4jStoragePipeline,
            LogPipeline,
        )
        
        # 根据 spider_type 选择爬虫
        if spider_type == "person":
            from crawler.spiders.person_spider import PersonSpider
            spider = PersonSpider(
                source=config.get("source", "baike"),
                keywords=keywords,
            )
        elif spider_type == "work":
            from crawler.spiders.work_spider import WorkSpider
            spider = WorkSpider(
                source=config.get("source", "douban"),
                keywords=keywords,
            )
        else:
            raise ValueError(f"Unknown spider type: {spider_type}")
        
        # 创建管道
        pipelines = [
            DataCleaningPipeline(),
            DataValidationPipeline(),
            DatabaseStoragePipeline(),
            Neo4jStoragePipeline(),
            LogPipeline(),
        ]
        
        # 创建引擎
        engine = CrawlerEngine(
            spider=spider,
            scheduler=Scheduler(),
            downloader=Downloader(
                concurrent_limit=config.get("concurrent_limit", 3),
                delay=config.get("delay", 1.0),
                timeout=config.get("timeout", 30),
            ),
            pipelines=pipelines,
            max_concurrent=config.get("concurrent_limit", 3),
        )
        
        # 启动引擎
        logger.info(f"Starting crawler engine for task: {task.id}")
        
        # 在后台运行引擎，同时更新进度
        engine_task = asyncio.create_task(engine.start())
        
        # 定期更新任务进度
        while not engine_task.done():
            await asyncio.sleep(2)
            stats = engine.get_stats()
            progress = min(95, stats["responses_received"] * 10)  # 粗略估算
            await self.update_task_progress(
                task.id,
                progress=progress,
                total_requests=stats["requests_scheduled"],
                success_count=stats["items_scraped"],
            )
        
        # 获取最终结果
        try:
            final_stats = await engine_task
            await self.update_task_progress(
                task.id,
                progress=100,
                total_requests=final_stats["requests_scheduled"],
                success_count=final_stats["items_scraped"],
            )
            logger.info(f"Crawler engine finished for task: {task.id}, stats: {final_stats}")
        except Exception as e:
            logger.error(f"Crawler engine failed for task: {task.id}, error: {e}")
            raise

    async def _execute_incremental_update(self, task: CrawlTask) -> None:
        """执行增量更新任务"""
        logger.info(f"Executing incremental update task: {task.id}")
        
        # TODO: 实现增量更新逻辑
        # 1. 获取上次更新时间
        # 2. 只爬取更新的内容
        # 3. 合并到现有数据
        
        await asyncio.sleep(1)  # 占位
        
        # 更新进度
        await self.update_task_progress(task.id, 100)

    async def _execute_targeted_crawl(self, task: CrawlTask) -> None:
        """执行定向爬取任务"""
        logger.info(f"Executing targeted crawl task: {task.id}")
        
        # 定向爬取使用与全量更新相同的引擎，但配置更具体
        config = task.config or {}
        
        # 定向爬取通常有明确的 targets
        targets = config.get("targets", [])
        if not targets:
            logger.warning(f"No targets provided for targeted crawl: {task.id}")
            return
        
        # 复用全量更新的逻辑
        config["keywords"] = targets
        await self._execute_full_update(task)

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
        """执行数据清洗任务"""
        logger.info(f"Executing cleanup task: {task.id}")
        
        # TODO: 实现数据清洗逻辑
        # 1. 清理重复数据
        # 2. 清理过期数据
        # 3. 优化索引
        
        await asyncio.sleep(1)  # 占位
        
        # 更新进度
        await self.update_task_progress(task.id, 100)

    async def _crawl_source(self, task: CrawlTask, source: CrawlSource) -> None:
        """
        执行单个爬取源的爬取（已废弃，使用 CrawlerEngine 替代）
        
        Args:
            task: 任务实例
            source: 爬取源实例
        """
        logger.info(f"Crawling source: {source.name} ({source.id})")
        
        # 记录开始日志
        await self.log_service.create_log({
            "task_id": task.id,
            "source_id": source.id,
            "level": "info",
            "stage": "fetch",
            "status": "started",
            "resource_url": source.base_url,
            "message": f"Started crawling source: {source.name}",
        })
        
        try:
            # 使用新的 CrawlerEngine 执行爬取
            config = task.config or {}
            keywords = config.get("keywords", [])
            
            if not keywords:
                logger.warning(f"No keywords for source: {source.id}")
                return
            
            # 创建爬虫
            from crawler.spiders.person_spider import PersonSpider
            spider = PersonSpider(
                source=source.code or "baike",
                keywords=keywords,
            )
            
            # 创建引擎
            from crawler.engine import CrawlerEngine, Scheduler, Downloader
            from crawler.pipelines import (
                DataCleaningPipeline,
                DataValidationPipeline,
                DatabaseStoragePipeline,
                LogPipeline,
            )
            
            engine = CrawlerEngine(
                spider=spider,
                scheduler=Scheduler(),
                downloader=Downloader(
                    concurrent_limit=source.concurrent_limit or 3,
                    delay=source.request_interval or 1.0,
                ),
                pipelines=[
                    DataCleaningPipeline(),
                    DataValidationPipeline(),
                    DatabaseStoragePipeline(),
                    LogPipeline(),
                ],
            )
            
            # 执行爬取
            stats = await engine.start()
            
            # 记录成功日志
            await self.log_service.create_log({
                "task_id": task.id,
                "source_id": source.id,
                "level": "success",
                "stage": "fetch",
                "status": "success",
                "resource_url": source.base_url,
                "message": f"Successfully crawled source: {source.name}, "
                           f"items={stats.get('items_scraped', 0)}, "
                           f"requests={stats.get('requests_scheduled', 0)}",
            })
            
            # 更新统计
            task.success_count = (task.success_count or 0) + stats.get("items_scraped", 0)
            
        except Exception as e:
            # 记录失败日志
            await self.log_service.create_log({
                "task_id": task.id,
                "source_id": source.id,
                "level": "error",
                "stage": "fetch",
                "status": "failed",
                "resource_url": source.base_url,
                "message": f"Failed to crawl source: {source.name}, error: {str(e)}",
            })
            
            # 更新统计
            task.failed_count = (task.failed_count or 0) + 1
        
        # 更新总请求数
        task.total_requests = (task.total_requests or 0) + 1
        await self.db.commit()
