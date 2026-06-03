"""数据备份脚本

定期备份Neo4j数据到JSON文件。
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from neo4j import GraphDatabase
except ImportError:
    print("Error: neo4j package not installed")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class DataBackup:
    """数据备份工具

    从Neo4j导出数据到JSON文件。
    """

    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        logger.info(f"Connected to Neo4j at {uri}")

    def export_persons(self) -> List[Dict[str, Any]]:
        """导出所有人物"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (p:Person)
                RETURN p {
                    .*,
                    id: p.id,
                    name: p.name,
                    name_en: p.name_en,
                    gender: p.gender,
                    birth_date: p.birth_date,
                    birth_place: p.birth_place,
                    nationality: p.nationality,
                    height: p.height,
                    summary: p.summary,
                    biography: p.biography,
                    popularity_score: p.popularity_score,
                    categories: p.categories
                } as person
            """)
            return [record["person"] for record in result]

    def export_works(self) -> List[Dict[str, Any]]:
        """导出所有作品"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (w:Work)
                RETURN w {
                    .*,
                    id: w.id,
                    title: w.title,
                    title_en: w.title_en,
                    type: w.type,
                    release_date: w.release_date,
                    genre: w.genre,
                    rating: w.rating,
                    poster: w.poster,
                    summary: w.summary
                } as work
            """)
            return [record["work"] for record in result]

    def export_relations(self) -> List[Dict[str, Any]]:
        """导出所有关系"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (a)-[r]->(b)
                RETURN {
                    source: a.id,
                    target: b.id,
                    type: type(r),
                    properties: properties(r)
                } as relation
            """)
            return [record["relation"] for record in result]

    def backup(self) -> Dict[str, Any]:
        """执行完整备份

        Returns:
            Dict: 备份数据
        """
        logger.info("Starting backup...")

        backup_data = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "version": "1.0",
            },
            "persons": self.export_persons(),
            "works": self.export_works(),
            "relations": self.export_relations(),
        }

        logger.info(
            f"Backup complete: {len(backup_data['persons'])} persons, "
            f"{len(backup_data['works'])} works, "
            f"{len(backup_data['relations'])} relations"
        )

        return backup_data

    def save_backup(self, data: Dict[str, Any], filepath: str):
        """保存备份到文件

        Args:
            data: 备份数据
            filepath: 文件路径
        """
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Backup saved to {filepath}")

    def close(self):
        """关闭连接"""
        self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Backup Neo4j data")
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
        "--output",
        default=f"backups/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        help="Output file path",
    )

    args = parser.parse_args()

    with DataBackup(args.uri, args.user, args.password) as backup:
        data = backup.backup()
        backup.save_backup(data, args.output)

        print(f"\nBackup saved to: {args.output}")
        print(f"Persons: {len(data['persons'])}")
        print(f"Works: {len(data['works'])}")
        print(f"Relations: {len(data['relations'])}")


if __name__ == "__main__":
    main()
