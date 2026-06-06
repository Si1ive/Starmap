"""
爬取源管理服务层

提供爬取源的 CRUD、健康检查、统计查询等业务逻辑。
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CrawlSource, CrawlSourceStats

logger = get_logger(__name__)


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
        source = CrawlSource(
            id=f"src_{uuid.uuid4().hex[:8]}",
            name=data["name"],
            code=data["code"],
            type=data.get("type"),
            base_url=data.get("base_url"),
            config=data.get("config"),
            request_interval=data.get("request_interval", 1.0),
            daily_limit=data.get("daily_limit", 1000),
            concurrent_limit=data.get("concurrent_limit", 5),
            status="active",
            health_status="healthy",
        )
        self.db.add(source)
        await self.db.commit()
        await self.db.refresh(source)
        logger.info(f"Created crawl source: {source.name} ({source.id})")
        return source

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
        try:
            response = requests.head(source.base_url, timeout=10)
            if response.status_code == 200:
                source.health_status = "healthy"
            else:
                source.health_status = "degraded"
        except Exception:
            source.health_status = "down"

        source.last_health_check = datetime.utcnow()
        await self.db.commit()

        return {
            "source_id": source_id,
            "status": source.health_status,
            "checked_at": source.last_health_check.isoformat(),
        }
