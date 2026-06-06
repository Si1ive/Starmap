"""
爬虫统计服务层

提供统计报表、趋势分析、效率分析等业务逻辑。
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CrawlLog, CrawlSource, CrawlSourceStats, CrawlTask, Person

logger = get_logger(__name__)


class CrawlerStatsService:
    """爬虫统计服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_overview(self) -> Dict[str, Any]:
        """获取总体概览"""
        # 活跃源数
        active_sources = await self.db.scalar(
            select(func.count()).where(CrawlSource.status == "active")
        ) or 0

        # 今日请求数
        today = datetime.now().date()
        today_requests = await self.db.scalar(
            select(func.coalesce(func.sum(CrawlSourceStats.total_requests), 0))
            .where(CrawlSourceStats.stat_date == today)
        ) or 0

        # 今日成功数
        today_success = await self.db.scalar(
            select(func.coalesce(func.sum(CrawlSourceStats.success_requests), 0))
            .where(CrawlSourceStats.stat_date == today)
        ) or 0

        # 整体成功率
        total_requests = await self.db.scalar(
            select(func.coalesce(func.sum(CrawlSourceStats.total_requests), 0))
        ) or 0
        total_success = await self.db.scalar(
            select(func.coalesce(func.sum(CrawlSourceStats.success_requests), 0))
        ) or 0
        total_failed = await self.db.scalar(
            select(func.coalesce(func.sum(CrawlSourceStats.failed_requests), 0))
        ) or 0
        total_tasks = await self.db.scalar(select(func.count(CrawlTask.id))) or 0

        success_rate = round(total_success / total_requests * 100, 2) if total_requests > 0 else 0
        recent_result = await self.db.execute(
            select(CrawlLog)
            .order_by(CrawlLog.created_at.desc())
            .limit(10)
        )
        recent_records = [
            {
                "id": log.id,
                "time": log.created_at.isoformat() if log.created_at else None,
                "resource": log.resource_name or log.resource_url or log.task_id,
                "action": log.action or log.stage or "-",
                "status": log.status or "pending",
                "duration": log.duration_ms or 0,
                "message": log.message,
            }
            for log in recent_result.scalars().all()
        ]
        category_result = await self.db.execute(
            select(Person.categories)
            .where(Person.categories.is_not(None))
            .order_by(Person.updated_at.desc())
            .limit(1000)
        )
        category_counts: Dict[str, int] = {}
        for categories in category_result.scalars().all():
            values = categories if isinstance(categories, list) else []
            for category in values:
                category_counts[str(category)] = category_counts.get(str(category), 0) + 1

        return {
            "active_sources": active_sources,
            "total_tasks": int(total_tasks),
            "today_requests": int(today_requests),
            "today_success": int(today_success),
            "today_success_rate": round(today_success / today_requests * 100, 2) if today_requests > 0 else 0,
            "total_requests": int(total_requests),
            "total_success": int(total_success),
            "total_failed": int(total_failed),
            "overall_success_rate": success_rate,
            "recent_records": recent_records,
            "category_distribution": [
                {"name": name, "value": value}
                for name, value in sorted(
                    category_counts.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:10]
            ],
        }

    async def get_source_comparison(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取各源对比数据"""
        start_date = datetime.now().date() - timedelta(days=days)

        query = (
            select(
                CrawlSource.id,
                CrawlSource.name,
                CrawlSource.type,
                CrawlSource.status,
                CrawlSource.health_status,
                func.coalesce(func.sum(CrawlSourceStats.total_requests), 0).label("total_requests"),
                func.coalesce(func.sum(CrawlSourceStats.success_requests), 0).label("success_requests"),
                func.coalesce(func.sum(CrawlSourceStats.failed_requests), 0).label("failed_requests"),
                func.avg(CrawlSourceStats.avg_response_time).label("avg_response_time"),
                func.avg(CrawlSourceStats.avg_completeness).label("avg_completeness"),
            )
            .outerjoin(
                CrawlSourceStats,
                and_(
                    CrawlSource.id == CrawlSourceStats.source_id,
                    CrawlSourceStats.stat_date >= start_date,
                ),
            )
            .group_by(CrawlSource.id)
        )

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "source_id": row.id,
                "name": row.name,
                "type": row.type,
                "status": row.status,
                "health_status": row.health_status,
                "total_requests": int(row.total_requests or 0),
                "success_requests": int(row.success_requests or 0),
                "failed_requests": int(row.failed_requests or 0),
                "success_rate": round(
                    (row.success_requests or 0) / (row.total_requests or 1) * 100, 2
                ),
                "avg_response_time": round(row.avg_response_time or 0, 2),
                "avg_completeness": round(row.avg_completeness or 0, 2),
            }
            for row in rows
        ]

    async def get_trend(self, days: int = 30) -> List[Dict[str, Any]]:
        """获取趋势数据"""
        start_date = datetime.now().date() - timedelta(days=days)

        query = (
            select(
                CrawlSourceStats.stat_date,
                func.coalesce(func.sum(CrawlSourceStats.total_requests), 0).label("requests"),
                func.coalesce(func.sum(CrawlSourceStats.success_requests), 0).label("successes"),
                func.coalesce(func.sum(CrawlSourceStats.failed_requests), 0).label("failures"),
            )
            .where(CrawlSourceStats.stat_date >= start_date)
            .group_by(CrawlSourceStats.stat_date)
            .order_by(CrawlSourceStats.stat_date)
        )

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "date": row.stat_date.isoformat(),
                "requests": int(row.requests or 0),
                "successes": int(row.successes or 0),
                "failures": int(row.failures or 0),
                "success_rate": round(
                    (row.successes or 0) / (row.requests or 1) * 100, 2
                ),
            }
            for row in rows
        ]

    async def get_efficiency(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取效率分析"""
        start_date = datetime.now().date() - timedelta(days=days)

        query = (
            select(
                CrawlSourceStats.source_id,
                CrawlSource.name,
                func.coalesce(func.sum(CrawlSourceStats.total_requests), 0).label("total_requests"),
                func.coalesce(func.sum(CrawlSourceStats.valid_records), 0).label("valid_records"),
                func.coalesce(func.sum(CrawlSourceStats.persons_extracted), 0).label("persons"),
                func.coalesce(func.sum(CrawlSourceStats.works_extracted), 0).label("works"),
                func.avg(CrawlSourceStats.avg_response_time).label("avg_response_time"),
                func.avg(CrawlSourceStats.avg_completeness).label("avg_completeness"),
            )
            .join(CrawlSource, CrawlSourceStats.source_id == CrawlSource.id)
            .where(CrawlSourceStats.stat_date >= start_date)
            .group_by(CrawlSourceStats.source_id)
        )

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "source_id": row.source_id,
                "name": row.name,
                "total_requests": int(row.total_requests or 0),
                "valid_records": int(row.valid_records or 0),
                "efficiency": round(
                    (row.valid_records or 0) / (row.total_requests or 1), 4
                ),
                "persons": int(row.persons or 0),
                "works": int(row.works or 0),
                "avg_response_time": round(row.avg_response_time or 0, 2),
                "avg_completeness": round(row.avg_completeness or 0, 2),
            }
            for row in rows
        ]
