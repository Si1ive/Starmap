"""
爬取源管理服务层

提供爬取源的 CRUD、健康检查、统计查询等业务逻辑。
"""

import asyncio
import time
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CrawlLog, CrawlSource, CrawlSourceStats

logger = get_logger(__name__)

DEFAULT_CRAWL_SOURCES = [
    {
        "id": "src_001",
        "name": "维基百科（中文）",
        "code": "wikipedia_zh",
        "type": "encyclopedia",
        "base_url": "https://zh.wikipedia.org/wiki/",
        "config": {
            "selectors": {
                "title": "h1.firstHeading",
                "summary": "div.mw-parser-output > p:first-of-type",
            },
            "anti_detection": {"user_agent_rotation": True, "delay_range": [1.0, 3.0]},
        },
        "request_interval": 1.0,
        "daily_limit": 1000,
        "concurrent_limit": 3,
    },
    {
        "id": "src_002",
        "name": "豆瓣电影",
        "code": "douban_movie",
        "type": "social",
        "base_url": "https://movie.douban.com/",
        "config": {
            "selectors": {
                "title": "span[property=\"v:itemreviewed\"]",
                "rating": "strong[property=\"v:average\"]",
            },
            "anti_detection": {"user_agent_rotation": True, "delay_range": [2.0, 5.0]},
        },
        "request_interval": 2.0,
        "daily_limit": 1000,
        "concurrent_limit": 2,
    },
    {
        "id": "src_003",
        "name": "百度百科",
        "code": "baidu_baike",
        "type": "encyclopedia",
        "base_url": "https://baike.baidu.com/",
        "config": {
            "selectors": {"title": "h1", "summary": ".lemma-summary"},
            "anti_detection": {"user_agent_rotation": True, "delay_range": [1.0, 3.0]},
        },
        "request_interval": 1.0,
        "daily_limit": 1000,
        "concurrent_limit": 3,
    },
]


class CrawlerSourceService:
    """爬取源管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_sources(
        self,
        skip: int = 0,
        limit: int = 20,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
    ) -> tuple[List[CrawlSource], int]:
        """获取爬取源列表（支持分页和筛选）"""
        await self.ensure_default_sources()
        query = select(CrawlSource)

        if status:
            query = query.where(CrawlSource.status == status)
        if source_type:
            query = query.where(CrawlSource.type == source_type)

        # 统计总数
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        # 分页查询
        query = query.offset(skip).limit(limit).order_by(CrawlSource.created_at.desc())
        result = await self.db.execute(query)
        sources = result.scalars().all()

        return list(sources), total

    async def get_source_by_id(self, source_id: str) -> Optional[CrawlSource]:
        """根据ID获取爬取源"""
        result = await self.db.execute(
            select(CrawlSource).where(CrawlSource.id == source_id)
        )
        return result.scalar_one_or_none()

    async def create_source(self, data: Dict[str, Any]) -> CrawlSource:
        """创建爬取源"""
        await self._ensure_source_tables()
        code = str(data["code"]).strip()
        result = await self.db.execute(
            select(CrawlSource).where(CrawlSource.code == code)
        )
        if result.scalar_one_or_none():
            raise ValueError(f"数据源编码已存在: {code}")

        source = CrawlSource(
            id=f"src_{uuid.uuid4().hex[:8]}",
            name=str(data["name"]).strip(),
            code=code,
            type=data.get("type"),
            base_url=data.get("base_url"),
            config=data.get("config"),
            request_interval=data.get("request_interval", 1.0),
            daily_limit=data.get("daily_limit", 1000),
            concurrent_limit=data.get("concurrent_limit", 5),
            status=data.get("status") or "active",
            health_status="healthy",
        )
        self.db.add(source)
        await self.db.commit()
        await self.db.refresh(source)
        logger.info(f"Created crawl source: {source.name} ({source.id})")
        return source

    async def ensure_default_sources(self) -> List[CrawlSource]:
        """确保核心默认爬取源存在"""
        await self._ensure_source_tables()
        result = await self.db.execute(
            select(CrawlSource).where(
                CrawlSource.code.in_([source["code"] for source in DEFAULT_CRAWL_SOURCES])
            )
        )
        existing_sources = result.scalars().all()
        existing_codes = {source.code for source in existing_sources}
        existing_ids = {source.id for source in existing_sources}
        created_sources: List[CrawlSource] = []

        for default_source in DEFAULT_CRAWL_SOURCES:
            if default_source["code"] in existing_codes:
                continue
            source_id = (
                default_source["id"]
                if default_source["id"] not in existing_ids
                else f"src_{uuid.uuid4().hex[:8]}"
            )
            source = CrawlSource(
                id=source_id,
                name=default_source["name"],
                code=default_source["code"],
                type=default_source["type"],
                base_url=default_source["base_url"],
                config=default_source["config"],
                request_interval=default_source["request_interval"],
                daily_limit=default_source["daily_limit"],
                concurrent_limit=default_source["concurrent_limit"],
                status="active",
                health_status="healthy",
            )
            self.db.add(source)
            created_sources.append(source)
            existing_ids.add(source_id)

        if created_sources:
            await self.db.commit()
            for source in created_sources:
                await self.db.refresh(source)
            logger.info("Initialized default crawl sources", count=len(created_sources))

        return [*existing_sources, *created_sources]

    async def _ensure_source_tables(self) -> None:
        """确保爬取源核心表存在"""
        await self.db.run_sync(
            lambda session: CrawlSource.__table__.create(
                bind=session.get_bind(),
                checkfirst=True,
            )
        )
        await self.db.run_sync(
            lambda session: CrawlSourceStats.__table__.create(
                bind=session.get_bind(),
                checkfirst=True,
            )
        )

    async def update_source(self, source_id: str, data: Dict[str, Any]) -> Optional[CrawlSource]:
        """更新爬取源"""
        source = await self.get_source_by_id(source_id)
        if not source:
            return None

        for key, value in data.items():
            if hasattr(source, key) and value is not None:
                setattr(source, key, value)

        source.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(source)
        logger.info(f"Updated crawl source: {source.name} ({source.id})")
        return source

    async def delete_source(self, source_id: str) -> bool:
        """删除爬取源（软删除，标记为 deprecated）"""
        source = await self.get_source_by_id(source_id)
        if not source:
            return False

        source.status = "deprecated"
        source.updated_at = datetime.utcnow()
        await self.db.commit()
        logger.info(f"Deprecated crawl source: {source.name} ({source.id})")
        return True

    async def get_source_stats(self, source_id: str, days: int = 30) -> Dict[str, Any]:
        """获取爬取源统计"""
        source = await self.get_source_by_id(source_id)
        if not source:
            return {"error": "Source not found"}

        # 查询日统计
        from datetime import timedelta
        start_date = datetime.now().date() - timedelta(days=days)

        result = await self.db.execute(
            select(CrawlSourceStats)
            .where(
                CrawlSourceStats.source_id == source_id,
                CrawlSourceStats.stat_date >= start_date,
            )
            .order_by(CrawlSourceStats.stat_date)
        )
        daily_stats = result.scalars().all()

        # 聚合计算
        total_requests = sum(s.total_requests for s in daily_stats)
        total_success = sum(s.success_requests for s in daily_stats)
        total_failed = sum(s.failed_requests for s in daily_stats)

        return {
            "source_id": source_id,
            "source_name": source.name,
            "total_requests": total_requests,
            "total_success": total_success,
            "total_failed": total_failed,
            "success_rate": round(total_success / total_requests * 100, 2) if total_requests > 0 else 0,
            "daily_stats": [
                {
                    "date": s.stat_date.isoformat(),
                    "requests": s.total_requests,
                    "success": s.success_requests,
                    "failed": s.failed_requests,
                    "persons": s.persons_extracted,
                    "works": s.works_extracted,
                    "avg_response_time": s.avg_response_time,
                    "completeness": s.avg_completeness,
                }
                for s in daily_stats
            ],
        }

    async def health_check(self, source_id: str) -> Dict[str, Any]:
        """爬取源健康检查"""
        source = await self.get_source_by_id(source_id)
        if not source:
            return {"status": "not_found", "source_id": source_id}

        import requests
        checked_at = datetime.utcnow()
        started_at = time.monotonic()
        http_status = None
        error_type = None
        error_detail = None
        health_task_id = f"health_{source_id[:25]}"

        try:
            if not source.base_url:
                raise ValueError("base_url is empty")

            response = await asyncio.to_thread(
                requests.head,
                source.base_url,
                timeout=10,
                allow_redirects=True,
            )
            http_status = response.status_code
            if http_status < 400:
                source.health_status = "healthy"
                log_level = "INFO"
                log_status = "success"
                message = f"Health check passed: HTTP {http_status}"
            elif http_status >= 500:
                source.health_status = "down"
                log_level = "ERROR"
                log_status = "failed"
                error_type = self._classify_http_error(http_status)
                error_detail = response.reason
                message = f"Health check failed: HTTP {http_status}"
            else:
                source.health_status = "degraded"
                log_level = "WARNING"
                log_status = "failed"
                error_type = self._classify_http_error(http_status)
                error_detail = response.reason
                message = f"Health check degraded: HTTP {http_status}"
        except Exception as e:
            source.health_status = "down"
            log_level = "ERROR"
            log_status = "failed"
            error_type = self._classify_request_error(e)
            error_detail = str(e)
            message = f"Health check failed: {error_detail}"

        duration_ms = int((time.monotonic() - started_at) * 1000)
        source.last_health_check = checked_at
        source.updated_at = checked_at
        if duration_ms > 0:
            source.avg_response_time = duration_ms
        self.db.add(CrawlLog(
            task_id=health_task_id,
            source_id=source_id,
            level=log_level,
            stage="health_check",
            resource_url=source.base_url,
            resource_name=source.name,
            resource_type="page",
            action="check",
            status=log_status,
            duration_ms=duration_ms,
            message=message,
            error_type=error_type,
            error_detail=error_detail,
            retry_count=0,
            details={
                "http_status": http_status,
                "health_status": source.health_status,
            },
        ))
        await self.db.commit()
        await self.db.refresh(source)

        return {
            "source_id": source_id,
            "status": source.health_status,
            "checked_at": source.last_health_check.isoformat(),
            "duration_ms": duration_ms,
            "http_status": http_status,
            "error_type": error_type,
            "error_detail": error_detail,
        }

    @staticmethod
    def _classify_http_error(status_code: int) -> str:
        """按 HTTP 状态码归类健康检查错误"""
        if status_code == 429:
            return "rate_limited"
        if 500 <= status_code < 600:
            return "upstream_5xx"
        if 400 <= status_code < 500:
            return "client_4xx"
        return "http_status_error"

    @staticmethod
    def _classify_request_error(error: Exception) -> str:
        """按 requests 异常归类健康检查错误"""
        import requests

        if isinstance(error, requests.Timeout):
            return "timeout"
        if isinstance(error, requests.ConnectionError):
            return "connection_error"
        if isinstance(error, ValueError):
            return "invalid_config"
        if isinstance(error, requests.RequestException):
            return "request_error"
        return error.__class__.__name__
