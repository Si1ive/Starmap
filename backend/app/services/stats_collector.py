"""
日统计数据采集服务

提供爬虫执行过程中的实时统计和数据汇总功能。
支持按天汇总统计数据，便于评估爬取源效果。
"""

from datetime import datetime, date
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CrawlSourceStats, CrawlLog

logger = get_logger(__name__)


class StatsCollector:
    """日统计数据采集器"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._daily_stats: Dict[str, Dict[str, Any]] = {}

    async def record_request(
        self,
        source_id: str,
        success: bool,
        response_time_ms: Optional[float] = None,
        error_type: Optional[str] = None,
    ) -> None:
        """
        记录一次请求统计
        
        Args:
            source_id: 爬取源ID
            success: 是否成功
            response_time_ms: 响应时间（毫秒）
            error_type: 错误类型（如果失败）
        """
        today = date.today().isoformat()
        key = f"{source_id}:{today}"
        
        if key not in self._daily_stats:
            self._daily_stats[key] = {
                "source_id": source_id,
                "stat_date": today,
                "total_requests": 0,
                "success_requests": 0,
                "failed_requests": 0,
                "timeout_requests": 0,
                "rate_limited_requests": 0,
                "response_times": [],
                "persons_extracted": 0,
                "works_extracted": 0,
                "relations_extracted": 0,
                "valid_records": 0,
                "duplicate_records": 0,
            }
        
        stats = self._daily_stats[key]
        stats["total_requests"] += 1
        
        if success:
            stats["success_requests"] += 1
        else:
            stats["failed_requests"] += 1
            if error_type == "timeout":
                stats["timeout_requests"] += 1
            elif error_type == "rate_limited":
                stats["rate_limited_requests"] += 1
        
        if response_time_ms is not None:
            stats["response_times"].append(response_time_ms)

    async def record_extraction(
        self,
        source_id: str,
        persons: int = 0,
        works: int = 0,
        relations: int = 0,
        valid: int = 0,
        duplicate: int = 0,
    ) -> None:
        """
        记录数据提取统计
        
        Args:
            source_id: 爬取源ID
            persons: 提取的人物数
            works: 提取的作品数
            relations: 提取的关系数
            valid: 有效记录数
            duplicate: 重复记录数
        """
        today = date.today().isoformat()
        key = f"{source_id}:{today}"
        
        if key not in self._daily_stats:
            self._daily_stats[key] = {
                "source_id": source_id,
                "stat_date": today,
                "total_requests": 0,
                "success_requests": 0,
                "failed_requests": 0,
                "timeout_requests": 0,
                "rate_limited_requests": 0,
                "response_times": [],
                "persons_extracted": 0,
                "works_extracted": 0,
                "relations_extracted": 0,
                "valid_records": 0,
                "duplicate_records": 0,
            }
        
        stats = self._daily_stats[key]
        stats["persons_extracted"] += persons
        stats["works_extracted"] += works
        stats["relations_extracted"] += relations
        stats["valid_records"] += valid
        stats["duplicate_records"] += duplicate

    async def flush_to_database(self) -> None:
        """
        将内存中的统计数据写入数据库
        
        应该在任务执行完成后调用。
        """
        if not self._daily_stats:
            return
        
        logger.info(f"Flushing {len(self._daily_stats)} daily stats to database")
        
        for key, stats in self._daily_stats.items():
            try:
                await self._upsert_stats(stats)
            except Exception as e:
                logger.error(f"Failed to flush stats for {key}: {e}")
        
        # 清空内存数据
        self._daily_stats.clear()
        
        logger.info("Daily stats flushed successfully")

    async def _upsert_stats(self, stats: Dict[str, Any]) -> None:
        """
        插入或更新日统计记录
        
        Args:
            stats: 统计数据字典
        """
        source_id = stats["source_id"]
        stat_date = stats["stat_date"]
        
        # 检查是否已存在
        result = await self.db.execute(
            select(CrawlSourceStats).where(
                and_(
                    CrawlSourceStats.source_id == source_id,
                    CrawlSourceStats.stat_date == stat_date,
                )
            )
        )
        existing = result.scalar_one_or_none()
        
        # 计算响应时间统计
        response_times = stats.get("response_times", [])
        if response_times:
            avg_response_time = sum(response_times) / len(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            # 计算 P95
            sorted_times = sorted(response_times)
            p95_index = int(len(sorted_times) * 0.95)
            p95_response_time = sorted_times[min(p95_index, len(sorted_times) - 1)]
        else:
            avg_response_time = None
            min_response_time = None
            max_response_time = None
            p95_response_time = None
        
        if existing:
            # 更新现有记录
            existing.total_requests += stats["total_requests"]
            existing.success_requests += stats["success_requests"]
            existing.failed_requests += stats["failed_requests"]
            existing.timeout_requests += stats["timeout_requests"]
            existing.rate_limited_requests += stats["rate_limited_requests"]
            existing.persons_extracted += stats["persons_extracted"]
            existing.works_extracted += stats["works_extracted"]
            existing.relations_extracted += stats["relations_extracted"]
            existing.valid_records += stats["valid_records"]
            existing.duplicate_records += stats["duplicate_records"]
            
            # 更新响应时间（加权平均）
            if avg_response_time is not None and existing.avg_response_time is not None:
                total_old = existing.total_requests - stats["total_requests"]
                if total_old > 0:
                    existing.avg_response_time = (
                        (existing.avg_response_time * total_old + avg_response_time * stats["total_requests"])
                        / existing.total_requests
                    )
                else:
                    existing.avg_response_time = avg_response_time
            elif avg_response_time is not None:
                existing.avg_response_time = avg_response_time
            
            if min_response_time is not None:
                existing.min_response_time = min(
                    existing.min_response_time or float('inf'),
                    min_response_time
                )
            
            if max_response_time is not None:
                existing.max_response_time = max(
                    existing.max_response_time or 0,
                    max_response_time
                )
            
            if p95_response_time is not None:
                existing.p95_response_time = p95_response_time
            
            logger.debug(f"Updated stats for {source_id} on {stat_date}")
        else:
            # 创建新记录
            new_stats = CrawlSourceStats(
                source_id=source_id,
                stat_date=stat_date,
                total_requests=stats["total_requests"],
                success_requests=stats["success_requests"],
                failed_requests=stats["failed_requests"],
                timeout_requests=stats["timeout_requests"],
                rate_limited_requests=stats["rate_limited_requests"],
                persons_extracted=stats["persons_extracted"],
                works_extracted=stats["works_extracted"],
                relations_extracted=stats["relations_extracted"],
                valid_records=stats["valid_records"],
                duplicate_records=stats["duplicate_records"],
                avg_response_time=avg_response_time,
                min_response_time=min_response_time,
                max_response_time=max_response_time,
                p95_response_time=p95_response_time,
            )
            self.db.add(new_stats)
            logger.debug(f"Created new stats for {source_id} on {stat_date}")
        
        await self.db.commit()

    async def get_source_stats(
        self,
        source_id: str,
        days: int = 7,
    ) -> List[Dict[str, Any]]:
        """
        获取爬取源的最近统计
        
        Args:
            source_id: 爬取源ID
            days: 最近天数
            
        Returns:
            统计列表
        """
        from datetime import timedelta
        
        start_date = (datetime.now() - timedelta(days=days)).date()
        
        result = await self.db.execute(
            select(CrawlSourceStats)
            .where(
                and_(
                    CrawlSourceStats.source_id == source_id,
                    CrawlSourceStats.stat_date >= start_date,
                )
            )
            .order_by(CrawlSourceStats.stat_date.desc())
        )
        
        stats = result.scalars().all()
        
        return [
            {
                "date": s.stat_date.isoformat(),
                "total_requests": s.total_requests,
                "success_requests": s.success_requests,
                "failed_requests": s.failed_requests,
                "success_rate": round(s.success_requests / s.total_requests * 100, 2) if s.total_requests > 0 else 0,
                "avg_response_time": s.avg_response_time,
                "persons_extracted": s.persons_extracted,
                "works_extracted": s.works_extracted,
            }
            for s in stats
        ]

    async def get_overview(self) -> Dict[str, Any]:
        """
        获取总体统计概览
        
        Returns:
            概览统计
        """
        today = date.today()
        
        # 今日统计
        today_result = await self.db.execute(
            select(
                func.sum(CrawlSourceStats.total_requests).label("total"),
                func.sum(CrawlSourceStats.success_requests).label("success"),
                func.sum(CrawlSourceStats.failed_requests).label("failed"),
                func.sum(CrawlSourceStats.persons_extracted).label("persons"),
                func.sum(CrawlSourceStats.works_extracted).label("works"),
            )
            .where(CrawlSourceStats.stat_date == today)
        )
        today_row = today_result.one()
        
        # 累计统计
        total_result = await self.db.execute(
            select(
                func.sum(CrawlSourceStats.total_requests).label("total"),
                func.sum(CrawlSourceStats.success_requests).label("success"),
                func.sum(CrawlSourceStats.persons_extracted).label("persons"),
            )
        )
        total_row = total_result.one()
        
        total_requests = total_row.total or 0
        success_requests = total_row.success or 0
        
        return {
            "today": {
                "requests": today_row.total or 0,
                "success": today_row.success or 0,
                "failed": today_row.failed or 0,
                "success_rate": round(success_requests / total_requests * 100, 2) if total_requests > 0 else 0,
                "persons": today_row.persons or 0,
                "works": today_row.works or 0,
            },
            "total": {
                "requests": total_requests,
                "success": success_requests,
                "success_rate": round(success_requests / total_requests * 100, 2) if total_requests > 0 else 0,
                "persons": total_row.persons or 0,
            },
        }
