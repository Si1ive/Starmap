"""
爬虫任务执行服务

提供爬虫任务的创建、执行、状态管理等核心功能。
集成 BaseCrawler 实现实际爬取逻辑。
"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CrawlTask, CrawlLog, CrawlSource
from app.services.log_service import CrawlerLogService
from app.services.scrapy_bridge import ScrapyBridgeService
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
        config = dict(target_config or {})
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
            sources, _ = await source_service.get_sources(skip=0, limit=1, status="active")
            source = sources[0] if sources else None
            if source:
                source_ids = [source.id]

        if task_type in {"full", "incremental", "targeted"}:
            if not source:
                raise ValueError("请选择有效的数据源")
            if not self._is_supported_source(config.get("spider_type", "github"), source.code):
                raise ValueError(f"{config.get('spider_type', 'github')} 爬虫暂不支持数据源 {source.name}")
            spider_type = config.get("spider_type", "github")
            if spider_type not in ("github", "knowledge") and not keywords:
                raise ValueError("请输入至少一个爬取关键词")

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
        aliases = {
            "wikipedia": "wikipedia_zh",
            "douban": "douban_movie",
            "baike": "baidu_baike",
        }
        return [code for code in {source_code, aliases.get(source_code)} if code]

    @staticmethod
    def _normalize_source_ids(source_ids: Any) -> List[str]:
        """Normalize source_ids input into a list."""
        if isinstance(source_ids, list):
            return [str(source_id) for source_id in source_ids if str(source_id).strip()]
        if isinstance(source_ids, str) and source_ids.strip():
            return [source_ids.strip()]
        return []

    @staticmethod
    def _normalize_keywords(keywords: Any) -> List[str]:
        """Normalize keyword input into a list."""
        if isinstance(keywords, list):
            return [str(keyword).strip() for keyword in keywords if str(keyword).strip()]
        if isinstance(keywords, str):
            return [keyword.strip() for keyword in keywords.split(",") if keyword.strip()]
        return []

    @staticmethod
    def _is_supported_source(spider_type: str, source_code: str) -> bool:
        """Check whether a Scrapy spider supports the selected source."""
        supported_sources = {
            "github": {"github"},
            "knowledge": {"github", "pdf"},
        }
        return source_code in supported_sources.get(spider_type, {source_code})

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
        """执行数据清洗任务"""
        logger.info(f"Executing cleanup task: {task.id}")
        
        config = task.config or {}
        cleanup_types = config.get("cleanup_types", ["duplicate", "expired", "orphan"])
        
        total_cleaned = 0
        
        # 1. 清理重复数据
        if "duplicate" in cleanup_types:
            await self.update_task_progress(task.id, 10)
            logger.info(f"Cleaning duplicates for task: {task.id}")
            
            from sqlalchemy import select, func
            from app.models.mysql_models import Person
            
            # 查找重复的人物（按名称分组）
            result = await self.db.execute(
                select(Person.name, func.count(Person.id).label("count"))
                .group_by(Person.name)
                .having(func.count(Person.id) > 1)
            )
            duplicates = result.all()
            
            duplicate_count = len(duplicates)
            logger.info(f"Found {duplicate_count} duplicate person names")
            
            # 合并重复数据（保留最新的一条）
            for name, count in duplicates:
                result = await self.db.execute(
                    select(Person)
                    .where(Person.name == name)
                    .order_by(Person.updated_at.desc())
                )
                persons = result.scalars().all()
                
                # 保留第一条（最新的），其余标记为删除
                for person in persons[1:]:
                    person.status = "deleted"
                    total_cleaned += 1
            
            await self.db.commit()
            logger.info(f"Cleaned {total_cleaned} duplicate records")
        
        # 2. 清理过期数据
        if "expired" in cleanup_types:
            await self.update_task_progress(task.id, 50)
            logger.info(f"Cleaning expired data for task: {task.id}")
            
            from datetime import timedelta
            from app.models.mysql_models import Person, Work
            
            # 清理超过 90 天未更新的 pending 数据
            expiry_date = datetime.utcnow() - timedelta(days=90)
            
            # 清理过期人物
            result = await self.db.execute(
                select(Person)
                .where(
                    Person.status == "pending",
                    Person.updated_at < expiry_date,
                )
            )
            expired_persons = result.scalars().all()
            for person in expired_persons:
                person.status = "deleted"
                total_cleaned += 1
            
            # 清理过期作品
            result = await self.db.execute(
                select(Work)
                .where(
                    Work.status == "pending",
                    Work.updated_at < expiry_date,
                )
            )
            expired_works = result.scalars().all()
            for work in expired_works:
                work.status = "deleted"
                total_cleaned += 1
            
            await self.db.commit()
            logger.info(f"Cleaned {len(expired_persons)} expired persons, {len(expired_works)} expired works")
        
        # 3. 清理孤立数据
        if "orphan" in cleanup_types:
            await self.update_task_progress(task.id, 80)
            logger.info(f"Cleaning orphan data for task: {task.id}")
            
            from app.models.mysql_models import PersonWork, PersonRelation
            
            # 清理指向已删除人物的关联
            result = await self.db.execute(
                select(PersonWork)
                .join(Person, PersonWork.person_id == Person.id)
                .where(Person.status == "deleted")
            )
            orphan_pws = result.scalars().all()
            for pw in orphan_pws:
                await self.db.delete(pw)
                total_cleaned += 1
            
            # 清理指向已删除人物的关系
            result = await self.db.execute(
                select(PersonRelation)
                .join(Person, PersonRelation.source_id == Person.id)
                .where(Person.status == "deleted")
            )
            orphan_rels = result.scalars().all()
            for rel in orphan_rels:
                await self.db.delete(rel)
                total_cleaned += 1
            
            await self.db.commit()
            logger.info(f"Cleaned {len(orphan_pws)} orphan person_works, {len(orphan_rels)} orphan relations")
        
        # 更新进度和统计
        await self.update_task_progress(task.id, 100)
        
        # 记录清洗结果
        await self.log_service.create_log({
            "task_id": task.id,
            "level": "INFO",
            "stage": "cleanup",
            "status": "success",
            "message": f"Cleanup completed: {total_cleaned} records cleaned",
        })
        
        logger.info(f"Cleanup task completed: {task.id}, total_cleaned={total_cleaned}")

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
            "level": "INFO",
            "stage": "fetch",
            "status": "pending",
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
                "level": "INFO",
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
                "level": "ERROR",
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
