"""
爬虫日志服务层

提供日志的查询、分析、写入等业务逻辑。
"""

import csv
import io
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import CrawlLog

logger = get_logger(__name__)

# 允许的 level 值（数据库枚举定义）
ALLOWED_LEVELS = {"INFO", "WARNING", "ERROR", "DEBUG", "SUCCESS", "CRITICAL"}

# 允许的 status 值（数据库枚举定义）
ALLOWED_STATUSES = {"success", "failed", "retry", "pending"}

LOG_EXPORT_FIELDS = [
    "id",
    "task_id",
    "source_id",
    "level",
    "stage",
    "resource_url",
    "resource_name",
    "resource_type",
    "action",
    "status",
    "duration_ms",
    "message",
    "error_type",
    "error_detail",
    "retry_count",
    "details",
    "created_at",
]


class CrawlerLogService:
    """爬虫日志服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_logs(
        self,
        task_id: Optional[str] = None,
        source_id: Optional[str] = None,
        level: Optional[str] = None,
        status: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[CrawlLog], int]:
        """获取日志列表（支持多维度筛选）"""
        query = select(CrawlLog)

        if task_id:
            query = query.where(CrawlLog.task_id == task_id)
        if source_id:
            query = query.where(CrawlLog.source_id == source_id)
        if level:
            query = query.where(CrawlLog.level == level)
        if status:
            query = query.where(CrawlLog.status == status)
        if resource_type:
            query = query.where(CrawlLog.resource_type == resource_type)
        if start_time:
            query = query.where(CrawlLog.created_at >= start_time)
        if end_time:
            query = query.where(CrawlLog.created_at <= end_time)

        # 统计总数
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        # 分页查询，按时间倒序
        query = query.order_by(desc(CrawlLog.created_at)).offset(skip).limit(limit)
        result = await self.db.execute(query)
        logs = result.scalars().all()

        return list(logs), total

    async def export_logs(
        self,
        task_id: Optional[str] = None,
        source_id: Optional[str] = None,
        level: Optional[str] = None,
        status: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 5000,
    ) -> tuple[List[Dict[str, Any]], int]:
        """导出日志列表（复用查询筛选条件）"""
        logs, total = await self.get_logs(
            task_id=task_id,
            source_id=source_id,
            level=level,
            status=status,
            resource_type=resource_type,
            start_time=start_time,
            end_time=end_time,
            skip=0,
            limit=limit,
        )
        return [self.serialize_log(log) for log in logs], total

    @staticmethod
    def serialize_log(log: CrawlLog) -> Dict[str, Any]:
        """序列化日志模型"""
        return {
            "id": log.id,
            "task_id": log.task_id,
            "source_id": log.source_id,
            "level": log.level,
            "stage": log.stage,
            "resource_url": log.resource_url,
            "resource_name": log.resource_name,
            "resource_type": log.resource_type,
            "action": log.action,
            "status": log.status,
            "duration_ms": log.duration_ms,
            "message": log.message,
            "error_type": log.error_type,
            "error_detail": log.error_detail,
            "retry_count": log.retry_count,
            "details": log.details,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }

    @staticmethod
    def to_csv(rows: List[Dict[str, Any]]) -> str:
        """转换日志导出行为 CSV 文本"""
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=LOG_EXPORT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: (
                    json.dumps(row.get(field), ensure_ascii=False, default=str)
                    if isinstance(row.get(field), (dict, list))
                    else row.get(field)
                )
                for field in LOG_EXPORT_FIELDS
            })
        return "\ufeff" + buffer.getvalue()

    async def create_log(self, data: Dict[str, Any]) -> Optional[CrawlLog]:
        """写入日志"""
        # 标准化 level 为大写，并映射到数据库允许的枚举值
        level = (data.get("level") or "INFO").upper()
        if level not in ALLOWED_LEVELS:
            # 映射不支持的 level 到允许的枚举
            level = "INFO"
        
        # 标准化 status 为枚举允许的值
        status = data.get("status")
        if status and status not in ALLOWED_STATUSES:
            # 映射常见状态值到允许的枚举
            status_map = {
                "started": "pending",
                "stopped": "failed",
                "skipped": "pending",
                "completed": "success",
                "error": "failed",
            }
            status = status_map.get(status, "pending")
        
        try:
            log = CrawlLog(
                task_id=data["task_id"],
                source_id=data.get("source_id"),
                level=level,
                stage=data.get("stage"),
                resource_url=data.get("resource_url"),
                resource_name=data.get("resource_name"),
                resource_type=data.get("resource_type"),
                action=data.get("action"),
                status=status,
                duration_ms=data.get("duration_ms"),
                message=data.get("message"),
                error_type=data.get("error_type"),
                error_detail=data.get("error_detail"),
                retry_count=data.get("retry_count", 0),
                details=data.get("details"),
            )
            self.db.add(log)
            await self.db.commit()
            await self.db.refresh(log)
            return log
        except Exception as e:
            logger.error(f"Failed to create crawl log: {e}, data={data}")
            await self.db.rollback()
            return None

    async def get_analysis(self, days: int = 7) -> Dict[str, Any]:
        """获取日志分析统计"""
        start_time = datetime.utcnow() - timedelta(days=days)

        # 按级别统计
        level_stats = await self.db.execute(
            select(
                CrawlLog.level,
                func.count().label("count"),
            )
            .where(CrawlLog.created_at >= start_time)
            .group_by(CrawlLog.level)
        )
        level_distribution = [
            {"level": row.level, "count": row.count}
            for row in level_stats.all()
        ]

        # 按状态统计
        status_stats = await self.db.execute(
            select(
                CrawlLog.status,
                func.count().label("count"),
            )
            .where(CrawlLog.created_at >= start_time)
            .group_by(CrawlLog.status)
        )
        status_distribution = [
            {"status": row.status, "count": row.count}
            for row in status_stats.all()
        ]

        # 按错误类型统计
        error_stats = await self.db.execute(
            select(
                CrawlLog.error_type,
                func.count().label("count"),
            )
            .where(
                CrawlLog.created_at >= start_time,
                CrawlLog.error_type.isnot(None),
            )
            .group_by(CrawlLog.error_type)
            .order_by(desc(func.count()))
            .limit(10)
        )
        error_distribution = [
            {"error_type": row.error_type, "count": row.count}
            for row in error_stats.all()
        ]

        # 按源统计
        source_stats = await self.db.execute(
            select(
                CrawlLog.source_id,
                func.count().label("count"),
                func.avg(CrawlLog.duration_ms).label("avg_duration"),
            )
            .where(CrawlLog.created_at >= start_time)
            .group_by(CrawlLog.source_id)
        )
        source_distribution = [
            {
                "source_id": row.source_id,
                "count": row.count,
                "avg_duration": round(row.avg_duration or 0, 2),
            }
            for row in source_stats.all()
        ]

        # 每日趋势
        daily_stats = await self.db.execute(
            select(
                func.date(CrawlLog.created_at).label("date"),
                func.count().label("total"),
                func.sum(func.if_(CrawlLog.status == "success", 1, 0)).label("success"),
                func.sum(func.if_(CrawlLog.status == "failed", 1, 0)).label("failed"),
            )
            .where(CrawlLog.created_at >= start_time)
            .group_by(func.date(CrawlLog.created_at))
            .order_by(func.date(CrawlLog.created_at))
        )
        daily_trend = [
            {
                "date": row.date.isoformat(),
                "total": row.total,
                "success": row.success,
                "failed": row.failed,
            }
            for row in daily_stats.all()
        ]

        return {
            "period_days": days,
            "level_distribution": level_distribution,
            "status_distribution": status_distribution,
            "error_distribution": error_distribution,
            "source_distribution": source_distribution,
            "daily_trend": daily_trend,
        }

    async def get_log_by_id(self, log_id: int) -> Optional[CrawlLog]:
        """根据ID获取日志详情"""
        result = await self.db.execute(
            select(CrawlLog).where(CrawlLog.id == log_id)
        )
        return result.scalar_one_or_none()
