"""数据初始化脚本

用于初始化测试数据、示例数据等。
"""

import os
import sys
import json
import logging
import argparse
from typing import List, Dict, Any
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crawler.models import Person, Work, Relation
from crawler.cleaner import DataCleaner
from crawler.validator import DataValidator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# 示例人物数据（用于测试）
SAMPLE_PERSONS = [
    {
        "id": "person_001",
        "name": "周杰伦",
        "name_en": "Jay Chou",
        "gender": "male",
        "birth_date": "1979-01-18",
        "birth_place": "台湾省新北市",
        "nationality": "中国",
        "summary": "华语流行乐男歌手、音乐人、演员、导演、编剧。",
        "categories": ["singer", "actor", "director"],
    },
    {
        "id": "person_002",
        "name": "昆凌",
        "name_en": "Hannah Quinlivan",
        "gender": "female",
        "birth_date": "1993-08-12",
        "birth_place": "台湾省台北市",
        "nationality": "中国",
        "summary": "中国台湾女模特、演员。",
        "categories": ["actor", "model"],
    },
    {
        "id": "person_003",
        "name": "方文山",
        "name_en": "Vincent Fang",
        "gender": "male",
        "birth_date": "1969-01-26",
        "birth_place": "台湾省花莲县",
        "nationality": "中国",
        "summary": "华语流行乐作词人、导演。",
        "categories": ["songwriter", "director"],
    },
]

# 示例作品数据
SAMPLE_WORKS = [
    {
        "id": "work_001",
        "title": "七里香",
        "type": "album",
        "release_date": "2004-08-03",
        "genre": "流行",
        "rating": 9.0,
    },
    {
        "id": "work_002",
        "title": "范特西",
        "type": "album",
        "release_date": "2001-09-14",
        "genre": "流行",
        "rating": 9.2,
    },
    {
        "id": "work_003",
        "title": "不能说的秘密",
        "type": "movie",
        "release_date": "2007-07-31",
        "genre": "爱情/音乐",
        "rating": 8.5,
    },
]

# 示例关系数据
SAMPLE_RELATIONS = [
    {
        "source": "person_001",
        "target": "person_002",
        "type": "MARRIED_TO",
        "properties": {"start_date": "2015-01-17"},
    },
    {
        "source": "person_001",
        "target": "person_003",
        "type": "COLLABORATED_WITH",
        "properties": {"times": 50},
    },
    {
        "source": "person_001",
        "target": "work_001",
        "type": "SINGS",
        "properties": {},
    },
    {
        "source": "person_001",
        "target": "work_002",
        "type": "SINGS",
        "properties": {},
    },
    {
        "source": "person_001",
        "target": "work_003",
        "type": "DIRECTED",
        "properties": {},
    },
]


def create_sample_data() -> Dict[str, Any]:
    """创建示例数据集

    Returns:
        Dict: 包含persons、works、relations的数据字典
    """
    cleaner = DataCleaner()
    validator = DataValidator()

    # 转换并清洗数据
    persons = [Person.from_dict(p) for p in SAMPLE_PERSONS]
    works = [Work.from_dict(w) for w in SAMPLE_WORKS]
    relations = [Relation.from_dict(r) for r in SAMPLE_RELATIONS]

    # 清洗
    persons = cleaner.clean_persons(persons)
    works = cleaner.clean_works(works)
    relations = cleaner.clean_relations(relations)

    # 验证
    report = validator.validate_dataset(persons, works, relations)

    if not report["summary"]["valid_persons"] == len(persons):
        logger.warning("Some persons failed validation")

    return {
        "persons": [p.to_dict() for p in persons],
        "works": [w.to_dict() for w in works],
        "relations": [r.to_dict() for r in relations],
        "validation_report": report,
    }


def save_data(data: Dict[str, Any], filepath: str):
    """保存数据到JSON文件

    Args:
        data: 数据字典
        filepath: 文件路径
    """
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Data saved to {filepath}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Initialize sample data")
    parser.add_argument(
        "--output",
        default="data/sample_data.json",
        help="Output file path",
    )
    parser.add_argument(
        "--format",
        choices=["json", "neo4j"],
        default="json",
        help="Output format",
    )

    args = parser.parse_args()

    # 创建示例数据
    logger.info("Creating sample data...")
    data = create_sample_data()

    # 保存数据
    if args.format == "json":
        save_data(data, args.output)
        print(f"\nSample data saved to: {args.output}")
        print(f"Persons: {len(data['persons'])}")
        print(f"Works: {len(data['works'])}")
        print(f"Relations: {len(data['relations'])}")

    elif args.format == "neo4j":
        # 导入到Neo4j
        try:
            from scripts.import_neo4j import Neo4jImporter

            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "password")

            persons = [Person.from_dict(p) for p in data["persons"]]
            works = [Work.from_dict(w) for w in data["works"]]
            relations = [Relation.from_dict(r) for r in data["relations"]]

            with Neo4jImporter(uri, user, password) as importer:
                report = importer.import_dataset(persons, works, relations)
                print("\nNeo4j Import Report:")
                print(json.dumps(report, indent=2, ensure_ascii=False))

        except ImportError:
            logger.error("neo4j package not installed")
            sys.exit(1)


if __name__ == "__main__":
    main()
