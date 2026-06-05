"""
作品管理服务层

提供作品的 CRUD、搜索、筛选等业务逻辑。
"""

from typing import List, Optional, Tuple
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import Work

logger = get_logger(__name__)


class WorkService:
    """作品管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_works(
        self,
        skip: int = 0,
        limit: int = 20,
        keyword: Optional[str] = None,
        work_type: Optional[str] = None,
        year: Optional[int] = None,
    ) -> Tuple[List[Work], int]:
        """
        获取作品列表
        
        Args:
            skip: 跳过数量
            limit: 限制数量
            keyword: 搜索关键词
            work_type: 作品类型
            year: 年份
            
        Returns:
            (作品列表, 总数)
        """
        query = select(Work)
        
        # 构建过滤条件
        filters = []
        
        if keyword:
            filters.append(
                or_(
                    Work.title.contains(keyword),
                    Work.title_en.contains(keyword),
                )
            )
        
        if work_type:
            filters.append(Work.type == work_type)
        
        if year:
            filters.append(Work.year == year)
        
        if filters:
            query = query.where(and_(*filters))
        
        # 统计总数
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0
        
        # 分页查询
        query = query.offset(skip).limit(limit).order_by(Work.created_at.desc())
        result = await self.db.execute(query)
        works = result.scalars().all()
        
        return list(works), total

    async def get_work_by_id(self, work_id: str) -> Optional[Work]:
        """
        根据ID获取作品
        
        Args:
            work_id: 作品ID
            
        Returns:
            作品实例或None
        """
        result = await self.db.execute(
            select(Work).where(Work.id == work_id)
        )
        return result.scalar_one_or_none()

    async def create_work(self, data: dict) -> Work:
        """
        创建作品
        
        Args:
            data: 作品数据
            
        Returns:
            创建的作品实例
        """
        import uuid
        
        work = Work(
            id=f"work_{uuid.uuid4().hex[:8]}",
            title=data.get("title"),
            title_en=data.get("title_en"),
            type=data.get("type"),
            release_date=data.get("release_date"),
            poster=data.get("poster"),
            rating=data.get("rating"),
            status=data.get("status", "active"),
            genre=data.get("genre"),
            summary=data.get("summary"),
        )
        
        self.db.add(work)
        await self.db.commit()
        await self.db.refresh(work)
        
        logger.info(f"Created work: {work.title} ({work.id})")
        return work

    async def update_work(self, work_id: str, data: dict) -> Optional[Work]:
        """
        更新作品
        
        Args:
            work_id: 作品ID
            data: 更新数据
            
        Returns:
            更新后的作品实例或None
        """
        work = await self.get_work_by_id(work_id)
        if not work:
            return None
        
        for key, value in data.items():
            if hasattr(work, key) and value is not None:
                setattr(work, key, value)
        
        await self.db.commit()
        await self.db.refresh(work)
        
        logger.info(f"Updated work: {work.title} ({work.id})")
        return work

    async def delete_work(self, work_id: str) -> bool:
        """
        删除作品
        
        Args:
            work_id: 作品ID
            
        Returns:
            是否成功
        """
        work = await self.get_work_by_id(work_id)
        if not work:
            return False
        
        await self.db.delete(work)
        await self.db.commit()
        
        logger.info(f"Deleted work: {work_id}")
        return True
