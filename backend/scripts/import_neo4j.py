"""Neo4j数据导入脚本

将清洗验证后的数据导入Neo4j图数据库。
支持人物、作品、关系等实体的导入。
"""

import os
import sys
import json
import logging
import argparse
from typing import List, Dict, Any, Optional
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from neo4j import GraphDatabase
except ImportError:
    print("Error: neo4j package not installed. Run: pip install neo4j")
    sys.exit(1)

from crawler.models import Person, Work, Relation

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class Neo4jImporter:
    """Neo4j数据导入器

    将结构化数据导入Neo4j图数据库。

    使用示例:
        >>> importer = Neo4jImporter("bolt://localhost:7687", "neo4j", "password")
        >>> importer.import_person(person)
        >>> importer.import_work(work)
        >>> importer.import_relation(relation)
        >>> importer.close()
    """

    def __init__(self, uri: str, user: str, password: str):
        """初始化导入器

        Args:
            uri: Neo4j连接URI
            user: 用户名
            password: 密码
        """
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        logger.info(f"Connected to Neo4j at {uri}")

    def create_constraints(self):
        """创建数据库约束和索引

        根据数据模型文档创建必要的约束和索引。
        """
        with self.driver.session() as session:
            # 创建唯一约束
            constraints = [
                "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
                "CREATE CONSTRAINT work_id IF NOT EXISTS FOR (w:Work) REQUIRE w.id IS UNIQUE",
                "CREATE CONSTRAINT company_id IF NOT EXISTS FOR (c:Company) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT award_id IF NOT EXISTS FOR (a:Award) REQUIRE a.id IS UNIQUE",
            ]

            for constraint in constraints:
                try:
                    session.run(constraint)
                    logger.info(f"Created constraint: {constraint}")
                except Exception as e:
                    logger.warning(f"Constraint creation skipped: {e}")

            # 创建索引
            indexes = [
                "CREATE INDEX person_name IF NOT EXISTS FOR (p:Person) ON (p.name)",
                "CREATE INDEX person_name_en IF NOT EXISTS FOR (p:Person) ON (p.name_en)",
                "CREATE INDEX work_title IF NOT EXISTS FOR (w:Work) ON (w.title)",
                "CREATE INDEX work_type IF NOT EXISTS FOR (w:Work) ON (w.type)",
            ]

            for index in indexes:
                try:
                    session.run(index)
                    logger.info(f"Created index: {index}")
                except Exception as e:
                    logger.warning(f"Index creation skipped: {e}")

    def import_person(self, person: Person) -> bool:
        """导入人物

        Args:
            person: 人物数据

        Returns:
            bool: 是否成功
        """
        try:
            with self.driver.session() as session:
                session.run(
                    """
                    MERGE (p:Person {id: $id})
                    SET p.name = $name,
                        p.name_en = $name_en,
                        p.avatar = $avatar,
                        p.gender = $gender,
                        p.birth_date = $birth_date,
                        p.birth_place = $birth_place,
                        p.nationality = $nationality,
                        p.height = $height,
                        p.summary = $summary,
                        p.biography = $biography,
                        p.popularity_score = $popularity_score,
                        p.categories = $categories,
                        p.updated_at = $updated_at
                    """,
                    person.to_dict(),
                )
                logger.info(f"Imported person: {person.name} ({person.id})")
                return True
        except Exception as e:
            logger.error(f"Failed to import person {person.name}: {e}")
            return False

    def import_work(self, work: Work) -> bool:
        """导入作品

        Args:
            work: 作品数据

        Returns:
            bool: 是否成功
        """
        try:
            with self.driver.session() as session:
                session.run(
                    """
                    MERGE (w:Work {id: $id})
                    SET w.title = $title,
                        w.title_en = $title_en,
                        w.type = $type,
                        w.release_date = $release_date,
                        w.genre = $genre,
                        w.rating = $rating,
                        w.poster = $poster,
                        w.summary = $summary,
                        w.updated_at = $updated_at
                    """,
                    work.to_dict(),
                )
                logger.info(f"Imported work: {work.title} ({work.id})")
                return True
        except Exception as e:
            logger.error(f"Failed to import work {work.title}: {e}")
            return False

    def import_relation(self, relation: Relation) -> bool:
        """导入关系

        Args:
            relation: 关系数据

        Returns:
            bool: 是否成功
        """
        try:
            with self.driver.session() as session:
                # 动态构建Cypher查询
                rel_type = relation.type
                props = relation.properties

                # 构建属性设置部分
                prop_sets = []
                params = {
                    "source": relation.source,
                    "target": relation.target,
                }

                for key, value in props.items():
                    param_key = f"prop_{key}"
                    prop_sets.append(f"r.{key} = ${param_key}")
                    params[param_key] = value

                set_clause = ", ".join(prop_sets) if prop_sets else ""

                cypher = f"""
                MATCH (a) WHERE a.id = $source
                MATCH (b) WHERE b.id = $target
                MERGE (a)-[r:{rel_type}]->(b)
                """

                if set_clause:
                    cypher += f"SET {set_clause}"

                session.run(cypher, params)
                logger.info(
                    f"Imported relation: {relation.source} -[{rel_type}]-> {relation.target}"
                )
                return True
        except Exception as e:
            logger.error(f"Failed to import relation {relation.type}: {e}")
            return False

    def import_persons(self, persons: List[Person]) -> Dict[str, int]:
        """批量导入人物

        Args:
            persons: 人物列表

        Returns:
            Dict[str, int]: 导入统计
        """
        success = 0
        failed = 0

        for person in persons:
            if self.import_person(person):
                success += 1
            else:
                failed += 1

        logger.info(f"Imported {success}/{len(persons)} persons")
        return {"success": success, "failed": failed}

    def import_works(self, works: List[Work]) -> Dict[str, int]:
        """批量导入作品

        Args:
            works: 作品列表

        Returns:
            Dict[str, int]: 导入统计
        """
        success = 0
        failed = 0

        for work in works:
            if self.import_work(work):
                success += 1
            else:
                failed += 1

        logger.info(f"Imported {success}/{len(works)} works")
        return {"success": success, "failed": failed}

    def import_relations(self, relations: List[Relation]) -> Dict[str, int]:
        """批量导入关系

        Args:
            relations: 关系列表

        Returns:
            Dict[str, int]: 导入统计
        """
        success = 0
        failed = 0

        for relation in relations:
            if self.import_relation(relation):
                success += 1
            else:
                failed += 1

        logger.info(f"Imported {success}/{len(relations)} relations")
        return {"success": success, "failed": failed}

    def import_dataset(
        self,
        persons: List[Person],
        works: List[Work],
        relations: List[Relation],
    ) -> Dict[str, Any]:
        """导入完整数据集

        按照正确的顺序导入：先实体，后关系。

        Args:
            persons: 人物列表
            works: 作品列表
            relations: 关系列表

        Returns:
            Dict: 导入报告
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "persons": {"total": len(persons), "success": 0, "failed": 0},
            "works": {"total": len(works), "success": 0, "failed": 0},
            "relations": {"total": len(relations), "success": 0, "failed": 0},
        }

        # 创建约束
        self.create_constraints()

        # 导入人物
        person_stats = self.import_persons(persons)
        report["persons"].update(person_stats)

        # 导入作品
        work_stats = self.import_works(works)
        report["works"].update(work_stats)

        # 导入关系
        relation_stats = self.import_relations(relations)
        report["relations"].update(relation_stats)

        logger.info("Dataset import complete")
        return report

    def clear_database(self, confirm: bool = False):
        """清空数据库

        危险操作！需要确认。

        Args:
            confirm: 是否确认清空
        """
        if not confirm:
            logger.warning("Database clear skipped (confirmation required)")
            return

        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            logger.info("Database cleared")

    def get_statistics(self) -> Dict[str, Any]:
        """获取数据库统计信息

        Returns:
            Dict: 统计信息
        """
        with self.driver.session() as session:
            # 节点统计
            node_result = session.run(
                """
                MATCH (n)
                RETURN labels(n)[0] as label, count(*) as count
                ORDER BY count DESC
                """
            )
            nodes = {record["label"]: record["count"] for record in node_result}

            # 关系统计
            rel_result = session.run(
                """
                MATCH ()-[r]->()
                RETURN type(r) as type, count(*) as count
                ORDER BY count DESC
                """
            )
            relations = {record["type"]: record["count"] for record in rel_result}

            return {
                "nodes": nodes,
                "relations": relations,
                "total_nodes": sum(nodes.values()),
                "total_relations": sum(relations.values()),
            }

    def close(self):
        """关闭连接"""
        self.driver.close()
        logger.info("Neo4j connection closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def load_json_data(filepath: str) -> Dict[str, Any]:
    """从JSON文件加载数据

    Args:
        filepath: 文件路径

    Returns:
        Dict: 数据字典
    """
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Import data into Neo4j")
    parser.add_argument(
        "--uri",
        default=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        help="Neo4j URI",
    )
    parser.add_argument(
        "--user",
        default=os.getenv("NEO4J_USER", "neo4j"),
        help="Neo4j username",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("NEO4J_PASSWORD", "password"),
        help="Neo4j password",
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Path to JSON data file",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear database before import",
    )

    args = parser.parse_args()

    # 加载数据
    logger.info(f"Loading data from {args.data}")
    data = load_json_data(args.data)

    # 转换数据
    persons = [Person.from_dict(p) for p in data.get("persons", [])]
    works = [Work.from_dict(w) for w in data.get("works", [])]
    relations = [Relation.from_dict(r) for r in data.get("relations", [])]

    logger.info(
        f"Loaded: {len(persons)} persons, {len(works)} works, {len(relations)} relations"
    )

    # 导入数据
    with Neo4jImporter(args.uri, args.user, args.password) as importer:
        if args.clear:
            importer.clear_database(confirm=True)

        report = importer.import_dataset(persons, works, relations)

        # 打印统计
        stats = importer.get_statistics()
        report["statistics"] = stats

        print("\n" + "=" * 50)
        print("Import Report")
        print("=" * 50)
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
