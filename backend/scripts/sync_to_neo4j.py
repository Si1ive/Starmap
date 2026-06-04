"""
MySQL 到 Neo4j 数据同步脚本

将 MySQL 中的结构化数据同步到 Neo4j 图数据库。
支持全量同步和增量同步。
"""

import os
import sys
import asyncio
import argparse
from typing import List, Dict, Any, Optional
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aiohttp
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.mysql import mysql_client, get_mysql_client
from app.db.neo4j import neo4j_client
from app.models.mysql_models import Person, PersonRelation, Work
from app.core.logging import get_logger

logger = get_logger(__name__)


class Neo4jSyncService:
    """Neo4j 同步服务
    
    负责将 MySQL 数据同步到 Neo4j 图数据库。
    
    使用示例:
        >>> sync_service = Neo4jSyncService()
        >>> await sync_service.sync_all_persons()
        >>> await sync_service.sync_all_relations()
    """
    
    def __init__(self):
        self.mysql = None
        self.neo4j = None
        
    async def initialize(self):
        """初始化数据库连接"""
        self.mysql = await get_mysql_client()
        if not neo4j_client._driver:
            await neo4j_client.connect()
        self.neo4j = neo4j_client
        logger.info("同步服务初始化完成")
    
    async def close(self):
        """关闭连接"""
        if self.neo4j:
            await self.neo4j.close()
    
    async def sync_person(self, person_id: str) -> bool:
        """
        同步单个人物到 Neo4j
        
        Args:
            person_id: 人物ID
            
        Returns:
            bool: 是否成功
        """
        try:
            # 从 MySQL 读取人物
            person = await self.mysql.get_by_id(Person, person_id)
            if not person:
                logger.warning(f"人物不存在: {person_id}")
                return False
            
            # 同步到 Neo4j
            await self.neo4j.execute_write(
                """
                MERGE (p:Person {id: $id})
                SET p.name = $name,
                    p.name_en = $name_en,
                    p.category = $category,
                    p.popularity_score = $popularity_score
                """,
                {
                    "id": person.id,
                    "name": person.name,
                    "name_en": person.name_en,
                    "category": person.categories[0] if person.categories else None,
                    "popularity_score": person.popularity_score,
                }
            )
            
            logger.info(f"同步人物到 Neo4j: {person.name} ({person.id})")
            return True
            
        except Exception as e:
            logger.error(f"同步人物失败: {person_id}", error=str(e))
            return False
    
    async def sync_work(self, work_id: str) -> bool:
        """
        同步单个作品到 Neo4j
        
        Args:
            work_id: 作品ID
            
        Returns:
            bool: 是否成功
        """
        try:
            work = await self.mysql.get_by_id(Work, work_id)
            if not work:
                logger.warning(f"作品不存在: {work_id}")
                return False
            
            await self.neo4j.execute_write(
                """
                MERGE (w:Work {id: $id})
                SET w.title = $title,
                    w.type = $type
                """,
                {
                    "id": work.id,
                    "title": work.title,
                    "type": work.type,
                }
            )
            
            logger.info(f"同步作品到 Neo4j: {work.title} ({work.id})")
            return True
            
        except Exception as e:
            logger.error(f"同步作品失败: {work_id}", error=str(e))
            return False
    
    async def sync_relation(self, relation_id: int) -> bool:
        """
        同步单条关系到 Neo4j
        
        Args:
            relation_id: 关系ID
            
        Returns:
            bool: 是否成功
        """
        try:
            relation = await self.mysql.get_by_id(PersonRelation, relation_id)
            if not relation:
                logger.warning(f"关系不存在: {relation_id}")
                return False
            
            # 确保源和目标人物存在
            await self.sync_person(relation.source_id)
            await self.sync_person(relation.target_id)
            
            # 构建属性
            props = relation.properties or {}
            prop_sets = []
            params = {
                "source_id": relation.source_id,
                "target_id": relation.target_id,
            }
            
            for key, value in props.items():
                param_key = f"prop_{key}"
                prop_sets.append(f"r.{key} = ${param_key}")
                params[param_key] = value
            
            set_clause = ", ".join(prop_sets) if prop_sets else ""
            
            cypher = f"""
            MATCH (a:Person {{id: $source_id}})
            MATCH (b:Person {{id: $target_id}})
            MERGE (a)-[r:{relation.relation_type}]->(b)
            """
            
            if set_clause:
                cypher += f"SET {set_clause}"
            
            await self.neo4j.execute_write(cypher, params)
            
            logger.info(
                f"同步关系到 Neo4j: {relation.source_id} -[{relation.relation_type}]-> {relation.target_id}"
            )
            return True
            
        except Exception as e:
            logger.error(f"同步关系失败: {relation_id}", error=str(e))
            return False
    
    async def sync_all_persons(self, batch_size: int = 100) -> Dict[str, int]:
        """
        同步所有人物到 Neo4j
        
        Args:
            batch_size: 每批处理数量
            
        Returns:
            Dict: 同步统计
        """
        stats = {"total": 0, "success": 0, "failed": 0}
        
        async with self.mysql.session() as session:
            # 获取所有人物ID
            result = await session.execute(select(Person.id))
            person_ids = [row[0] for row in result.all()]
            
            stats["total"] = len(person_ids)
            logger.info(f"开始同步 {len(person_ids)} 个人物到 Neo4j")
            
            # 分批处理
            for i in range(0, len(person_ids), batch_size):
                batch = person_ids[i:i + batch_size]
                
                for person_id in batch:
                    if await self.sync_person(person_id):
                        stats["success"] += 1
                    else:
                        stats["failed"] += 1
                
                logger.info(f"已同步 {min(i + batch_size, len(person_ids))}/{len(person_ids)} 个人物")
        
        logger.info(f"人物同步完成: {stats}")
        return stats
    
    async def sync_all_works(self, batch_size: int = 100) -> Dict[str, int]:
        """
        同步所有作品到 Neo4j
        
        Args:
            batch_size: 每批处理数量
            
        Returns:
            Dict: 同步统计
        """
        stats = {"total": 0, "success": 0, "failed": 0}
        
        async with self.mysql.session() as session:
            result = await session.execute(select(Work.id))
            work_ids = [row[0] for row in result.all()]
            
            stats["total"] = len(work_ids)
            logger.info(f"开始同步 {len(work_ids)} 个作品到 Neo4j")
            
            for i in range(0, len(work_ids), batch_size):
                batch = work_ids[i:i + batch_size]
                
                for work_id in batch:
                    if await self.sync_work(work_id):
                        stats["success"] += 1
                    else:
                        stats["failed"] += 1
                
                logger.info(f"已同步 {min(i + batch_size, len(work_ids))}/{len(work_ids)} 个作品")
        
        logger.info(f"作品同步完成: {stats}")
        return stats
    
    async def sync_all_relations(self, batch_size: int = 100) -> Dict[str, int]:
        """
        同步所有关系到 Neo4j
        
        Args:
            batch_size: 每批处理数量
            
        Returns:
            Dict: 同步统计
        """
        stats = {"total": 0, "success": 0, "failed": 0}
        
        async with self.mysql.session() as session:
            result = await session.execute(select(PersonRelation.id))
            relation_ids = [row[0] for row in result.all()]
            
            stats["total"] = len(relation_ids)
            logger.info(f"开始同步 {len(relation_ids)} 条关系到 Neo4j")
            
            for i in range(0, len(relation_ids), batch_size):
                batch = relation_ids[i:i + batch_size]
                
                for relation_id in batch:
                    if await self.sync_relation(relation_id):
                        stats["success"] += 1
                    else:
                        stats["failed"] += 1
                
                logger.info(f"已同步 {min(i + batch_size, len(relation_ids))}/{len(relation_ids)} 条关系")
        
        logger.info(f"关系同步完成: {stats}")
        return stats
    
    async def sync_person_works(self) -> Dict[str, int]:
        """
        同步人物-作品关系到 Neo4j
        
        Returns:
            Dict: 同步统计
        """
        stats = {"total": 0, "success": 0, "failed": 0}
        
        async with self.mysql.session() as session:
            from app.models.mysql_models import PersonWork
            
            result = await session.execute(
                select(PersonWork).where(PersonWork.role_type.in_(["actor", "director", "singer"]))
            )
            person_works = result.scalars().all()
            
            stats["total"] = len(person_works)
            logger.info(f"开始同步 {len(person_works)} 个人物-作品关系到 Neo4j")
            
            for pw in person_works:
                try:
                    # 映射 role_type 到 Neo4j 关系类型
                    rel_type_map = {
                        "actor": "ACTED_IN",
                        "director": "DIRECTED",
                        "singer": "SINGS",
                    }
                    rel_type = rel_type_map.get(pw.role_type, "RELATED_TO")
                    
                    await self.neo4j.execute_write(
                        f"""
                        MATCH (p:Person {{id: $person_id}})
                        MATCH (w:Work {{id: $work_id}})
                        MERGE (p)-[r:{rel_type}]->(w)
                        SET r.role = $role, r.is_lead = $is_lead
                        """,
                        {
                            "person_id": pw.person_id,
                            "work_id": pw.work_id,
                            "role": pw.role,
                            "is_lead": pw.is_lead,
                        }
                    )
                    
                    stats["success"] += 1
                    
                except Exception as e:
                    logger.error(
                        f"同步人物-作品关系失败: {pw.person_id} - {pw.work_id}",
                        error=str(e)
                    )
                    stats["failed"] += 1
        
        logger.info(f"人物-作品关系同步完成: {stats}")
        return stats
    
    async def full_sync(self) -> Dict[str, Any]:
        """
        执行全量同步
        
        Returns:
            Dict: 同步报告
        """
        start_time = datetime.now()
        logger.info("开始全量同步到 Neo4j")
        
        report = {
            "start_time": start_time.isoformat(),
            "persons": await self.sync_all_persons(),
            "works": await self.sync_all_works(),
            "relations": await self.sync_all_relations(),
            "person_works": await self.sync_person_works(),
        }
        
        end_time = datetime.now()
        report["end_time"] = end_time.isoformat()
        report["duration_seconds"] = (end_time - start_time).total_seconds()
        
        logger.info(f"全量同步完成，耗时: {report['duration_seconds']}秒")
        return report
    
    async def incremental_sync(self, since: datetime) -> Dict[str, Any]:
        """
        执行增量同步
        
        Args:
            since: 同步起始时间
            
        Returns:
            Dict: 同步报告
        """
        start_time = datetime.now()
        logger.info(f"开始增量同步到 Neo4j，起始时间: {since}")
        
        report = {
            "start_time": start_time.isoformat(),
            "since": since.isoformat(),
            "persons": {"total": 0, "success": 0, "failed": 0},
            "works": {"total": 0, "success": 0, "failed": 0},
            "relations": {"total": 0, "success": 0, "failed": 0},
        }
        
        # 同步更新的人物
        async with self.mysql.session() as session:
            result = await session.execute(
                select(Person.id).where(Person.updated_at >= since)
            )
            person_ids = [row[0] for row in result.all()]
            
            report["persons"]["total"] = len(person_ids)
            for person_id in person_ids:
                if await self.sync_person(person_id):
                    report["persons"]["success"] += 1
                else:
                    report["persons"]["failed"] += 1
        
        # 同步更新的作品
        async with self.mysql.session() as session:
            result = await session.execute(
                select(Work.id).where(Work.updated_at >= since)
            )
            work_ids = [row[0] for row in result.all()]
            
            report["works"]["total"] = len(work_ids)
            for work_id in work_ids:
                if await self.sync_work(work_id):
                    report["works"]["success"] += 1
                else:
                    report["works"]["failed"] += 1
        
        # 同步更新的关系
        async with self.mysql.session() as session:
            result = await session.execute(
                select(PersonRelation.id).where(PersonRelation.updated_at >= since)
            )
            relation_ids = [row[0] for row in result.all()]
            
            report["relations"]["total"] = len(relation_ids)
            for relation_id in relation_ids:
                if await self.sync_relation(relation_id):
                    report["relations"]["success"] += 1
                else:
                    report["relations"]["failed"] += 1
        
        end_time = datetime.now()
        report["end_time"] = end_time.isoformat()
        report["duration_seconds"] = (end_time - start_time).total_seconds()
        
        logger.info(f"增量同步完成，耗时: {report['duration_seconds']}秒")
        return report


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Sync MySQL data to Neo4j")
    parser.add_argument(
        "--full",
        action="store_true",
        help="执行全量同步"
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="执行增量同步"
    )
    parser.add_argument(
        "--since",
        type=str,
        help="增量同步起始时间 (ISO格式，如 2024-01-01T00:00:00)"
    )
    parser.add_argument(
        "--persons-only",
        action="store_true",
        help="仅同步人物"
    )
    parser.add_argument(
        "--relations-only",
        action="store_true",
        help="仅同步关系"
    )
    
    args = parser.parse_args()
    
    sync_service = Neo4jSyncService()
    await sync_service.initialize()
    
    try:
        if args.full:
            report = await sync_service.full_sync()
            print("\n" + "=" * 50)
            print("全量同步报告")
            print("=" * 50)
            import json
            print(json.dumps(report, indent=2, ensure_ascii=False))
            
        elif args.incremental:
            if not args.since:
                print("错误: 增量同步需要 --since 参数")
                return
            
            since = datetime.fromisoformat(args.since)
            report = await sync_service.incremental_sync(since)
            print("\n" + "=" * 50)
            print("增量同步报告")
            print("=" * 50)
            import json
            print(json.dumps(report, indent=2, ensure_ascii=False))
            
        elif args.persons_only:
            stats = await sync_service.sync_all_persons()
            print(f"人物同步完成: {stats}")
            
        elif args.relations_only:
            stats = await sync_service.sync_all_relations()
            print(f"关系同步完成: {stats}")
            
        else:
            print("请指定同步模式: --full, --incremental, --persons-only, --relations-only")
            
    finally:
        await sync_service.close()


if __name__ == "__main__":
    asyncio.run(main())
