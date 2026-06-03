"""数据验证模块

提供数据完整性、正确性验证功能。
所有数据在导入前必须通过验证。
"""

import re
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

from .models import Person, Work, Relation, VALID_RELATION_TYPES, VALID_WORK_TYPES, VALID_GENDERS

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """验证错误"""

    def __init__(self, field: str, message: str, value: Any = None):
        self.field = field
        self.message = message
        self.value = value
        super().__init__(f"[{field}] {message}")


class ValidationResult:
    """验证结果"""

    def __init__(self):
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []

    @property
    def is_valid(self) -> bool:
        """是否验证通过（无错误）"""
        return len(self.errors) == 0

    @property
    def has_warnings(self) -> bool:
        """是否有警告"""
        return len(self.warnings) > 0

    def add_error(self, field: str, message: str, value: Any = None):
        """添加错误"""
        self.errors.append(ValidationError(field, message, value))

    def add_warning(self, field: str, message: str, value: Any = None):
        """添加警告"""
        self.warnings.append(ValidationError(field, message, value))

    def merge(self, other: "ValidationResult"):
        """合并另一个验证结果"""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [
                {"field": e.field, "message": e.message, "value": str(e.value)}
                for e in self.errors
            ],
            "warnings": [
                {"field": w.field, "message": w.message, "value": str(w.value)}
                for w in self.warnings
            ],
        }

    def __repr__(self):
        status = "VALID" if self.is_valid else "INVALID"
        return f"ValidationResult({status}, errors={len(self.errors)}, warnings={len(self.warnings)})"


class DataValidator:
    """数据验证器

    验证人物、作品、关系数据的完整性和正确性。

    使用示例:
        >>> validator = DataValidator()
        >>> result = validator.validate_person(person)
        >>> if not result.is_valid:
        ...     print(result.errors)
    """

    # 必填字段
    PERSON_REQUIRED_FIELDS = ["id", "name", "summary"]
    WORK_REQUIRED_FIELDS = ["id", "title", "type"]
    RELATION_REQUIRED_FIELDS = ["source", "target", "type"]

    # 字段长度限制
    MIN_NAME_LENGTH = 2
    MAX_NAME_LENGTH = 100
    MAX_SUMMARY_LENGTH = 2000
    MAX_BIOGRAPHY_LENGTH = 10000

    # 数值范围
    MIN_POPULARITY_SCORE = 0
    MAX_POPULARITY_SCORE = 100
    MIN_RATING = 0
    MAX_RATING = 10
    MIN_HEIGHT = 50
    MAX_HEIGHT = 300

    # ID格式
    PERSON_ID_PATTERN = re.compile(r"^person_[a-zA-Z0-9]+$")
    WORK_ID_PATTERN = re.compile(r"^work_[a-zA-Z0-9]+$")

    def __init__(self):
        """初始化验证器"""
        logger.info("DataValidator initialized")

    def validate_person(self, person: Person) -> ValidationResult:
        """验证人物数据

        Args:
            person: 人物数据

        Returns:
            ValidationResult: 验证结果
        """
        result = ValidationResult()
        data = person.to_dict()

        # 检查必填字段
        for field in self.PERSON_REQUIRED_FIELDS:
            if not data.get(field):
                result.add_error(field, f"必填字段缺失", data.get(field))

        # 验证ID格式
        if data.get("id"):
            if not self.PERSON_ID_PATTERN.match(data["id"]):
                result.add_error("id", "人物ID格式错误，应为 person_xxx", data["id"])

        # 验证姓名
        if data.get("name"):
            name = data["name"]
            if len(name) < self.MIN_NAME_LENGTH:
                result.add_error("name", f"姓名长度至少{self.MIN_NAME_LENGTH}个字符", name)
            if len(name) > self.MAX_NAME_LENGTH:
                result.add_error("name", f"姓名长度超过{self.MAX_NAME_LENGTH}个字符", name)

        # 验证性别
        if data.get("gender") is not None:
            if data["gender"] not in VALID_GENDERS:
                result.add_error("gender", f"无效的性别值: {data['gender']}", data["gender"])

        # 验证出生日期
        if data.get("birth_date"):
            if not self._is_valid_date(data["birth_date"]):
                result.add_error("birth_date", "无效的日期格式", data["birth_date"])

        # 验证身高
        if data.get("height") is not None:
            height = data["height"]
            if not (self.MIN_HEIGHT <= height <= self.MAX_HEIGHT):
                result.add_error(
                    "height",
                    f"身高应在{self.MIN_HEIGHT}-{self.MAX_HEIGHT}cm之间",
                    height,
                )

        # 验证知名度评分
        if data.get("popularity_score") is not None:
            score = data["popularity_score"]
            if not (self.MIN_POPULARITY_SCORE <= score <= self.MAX_POPULARITY_SCORE):
                result.add_error(
                    "popularity_score",
                    f"评分应在{self.MIN_POPULARITY_SCORE}-{self.MAX_POPULARITY_SCORE}之间",
                    score,
                )

        # 验证摘要长度
        if data.get("summary"):
            if len(data["summary"]) > self.MAX_SUMMARY_LENGTH:
                result.add_warning(
                    "summary",
                    f"摘要长度超过{self.MAX_SUMMARY_LENGTH}字符",
                    len(data["summary"]),
                )

        # 验证传记长度
        if data.get("biography"):
            if len(data["biography"]) > self.MAX_BIOGRAPHY_LENGTH:
                result.add_warning(
                    "biography",
                    f"传记长度超过{self.MAX_BIOGRAPHY_LENGTH}字符",
                    len(data["biography"]),
                )

        # 验证分类
        if data.get("categories"):
            if not isinstance(data["categories"], list):
                result.add_error("categories", "分类必须是列表", type(data["categories"]))

        logger.info(f"Validated person {person.name}: {result}")
        return result

    def validate_work(self, work: Work) -> ValidationResult:
        """验证作品数据

        Args:
            work: 作品数据

        Returns:
            ValidationResult: 验证结果
        """
        result = ValidationResult()
        data = work.to_dict()

        # 检查必填字段
        for field in self.WORK_REQUIRED_FIELDS:
            if not data.get(field):
                result.add_error(field, f"必填字段缺失", data.get(field))

        # 验证ID格式
        if data.get("id"):
            if not self.WORK_ID_PATTERN.match(data["id"]):
                result.add_error("id", "作品ID格式错误，应为 work_xxx", data["id"])

        # 验证标题
        if data.get("title"):
            title = data["title"]
            if len(title) < 1:
                result.add_error("title", "作品标题不能为空", title)
            if len(title) > self.MAX_NAME_LENGTH:
                result.add_error("title", f"标题长度超过{self.MAX_NAME_LENGTH}个字符", title)

        # 验证类型
        if data.get("type"):
            if data["type"] not in VALID_WORK_TYPES:
                result.add_error("type", f"无效的作品类型: {data['type']}", data["type"])

        # 验证发布日期
        if data.get("release_date"):
            if not self._is_valid_date(data["release_date"]):
                result.add_error("release_date", "无效的日期格式", data["release_date"])

        # 验证评分
        if data.get("rating") is not None:
            rating = data["rating"]
            if not (self.MIN_RATING <= rating <= self.MAX_RATING):
                result.add_error(
                    "rating",
                    f"评分应在{self.MIN_RATING}-{self.MAX_RATING}之间",
                    rating,
                )

        logger.info(f"Validated work {work.title}: {result}")
        return result

    def validate_relation(self, relation: Relation) -> ValidationResult:
        """验证关系数据

        Args:
            relation: 关系数据

        Returns:
            ValidationResult: 验证结果
        """
        result = ValidationResult()
        data = relation.to_dict()

        # 检查必填字段
        for field in self.RELATION_REQUIRED_FIELDS:
            if not data.get(field):
                result.add_error(field, f"必填字段缺失", data.get(field))

        # 验证不能自环
        if data.get("source") and data.get("target"):
            if data["source"] == data["target"]:
                result.add_error("source/target", "关系不能指向自身", data["source"])

        # 验证关系类型
        if data.get("type"):
            if data["type"] not in VALID_RELATION_TYPES:
                result.add_error("type", f"无效的关系类型: {data['type']}", data["type"])

        # 验证属性
        if data.get("properties"):
            if not isinstance(data["properties"], dict):
                result.add_error("properties", "属性必须是字典", type(data["properties"]))

        logger.info(f"Validated relation {relation.type}: {result}")
        return result

    def validate_persons(self, persons: List[Person]) -> Dict[str, ValidationResult]:
        """批量验证人物数据

        Args:
            persons: 人物列表

        Returns:
            Dict[str, ValidationResult]: 每个人物的验证结果
        """
        results = {}
        for person in persons:
            results[person.id] = self.validate_person(person)

        # 检查ID重复
        ids = [p.id for p in persons]
        duplicates = set([x for x in ids if ids.count(x) > 1])
        if duplicates:
            for dup_id in duplicates:
                results[dup_id].add_error("id", f"重复的ID: {dup_id}", dup_id)

        logger.info(f"Validated {len(persons)} persons")
        return results

    def validate_works(self, works: List[Work]) -> Dict[str, ValidationResult]:
        """批量验证作品数据

        Args:
            works: 作品列表

        Returns:
            Dict[str, ValidationResult]: 每个作品的验证结果
        """
        results = {}
        for work in works:
            results[work.id] = self.validate_work(work)

        # 检查ID重复
        ids = [w.id for w in works]
        duplicates = set([x for x in ids if ids.count(x) > 1])
        if duplicates:
            for dup_id in duplicates:
                results[dup_id].add_error("id", f"重复的ID: {dup_id}", dup_id)

        logger.info(f"Validated {len(works)} works")
        return results

    def validate_relations(self, relations: List[Relation]) -> List[ValidationResult]:
        """批量验证关系数据

        Args:
            relations: 关系列表

        Returns:
            List[ValidationResult]: 验证结果列表
        """
        results = []
        for relation in relations:
            results.append(self.validate_relation(relation))

        logger.info(f"Validated {len(relations)} relations")
        return results

    def validate_dataset(
        self,
        persons: List[Person],
        works: List[Work],
        relations: List[Relation],
    ) -> Dict[str, Any]:
        """验证整个数据集

        检查实体引用一致性等跨实体问题。

        Args:
            persons: 人物列表
            works: 作品列表
            relations: 关系列表

        Returns:
            Dict: 综合验证报告
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_persons": len(persons),
                "total_works": len(works),
                "total_relations": len(relations),
            },
            "persons": {},
            "works": {},
            "relations": [],
            "cross_entity_issues": [],
        }

        # 验证各类实体
        person_results = self.validate_persons(persons)
        work_results = self.validate_works(works)
        relation_results = self.validate_relations(relations)

        # 统计
        person_valid = sum(1 for r in person_results.values() if r.is_valid)
        work_valid = sum(1 for r in work_results.values() if r.is_valid)
        relation_valid = sum(1 for r in relation_results if r.is_valid)

        report["summary"]["valid_persons"] = person_valid
        report["summary"]["valid_works"] = work_valid
        report["summary"]["valid_relations"] = relation_valid

        # 转换结果
        report["persons"] = {
            k: v.to_dict() for k, v in person_results.items()
        }
        report["works"] = {
            k: v.to_dict() for k, v in work_results.items()
        }
        report["relations"] = [r.to_dict() for r in relation_results]

        # 检查跨实体引用一致性
        person_ids = {p.id for p in persons}
        work_ids = {w.id for w in works}

        for relation in relations:
            # 检查源实体是否存在
            if relation.source not in person_ids and relation.source not in work_ids:
                report["cross_entity_issues"].append({
                    "type": "missing_source",
                    "relation_type": relation.type,
                    "source": relation.source,
                    "message": f"关系源实体不存在: {relation.source}",
                })

            # 检查目标实体是否存在
            if relation.target not in person_ids and relation.target not in work_ids:
                report["cross_entity_issues"].append({
                    "type": "missing_target",
                    "relation_type": relation.type,
                    "target": relation.target,
                    "message": f"关系目标实体不存在: {relation.target}",
                })

        # 计算完整率
        if persons:
            completeness = self._calculate_completeness(persons)
            report["summary"]["completeness_rate"] = completeness

        logger.info(
            f"Dataset validation complete: "
            f"persons={person_valid}/{len(persons)}, "
            f"works={work_valid}/{len(works)}, "
            f"relations={relation_valid}/{len(relations)}"
        )

        return report

    def _is_valid_date(self, date_str: str) -> bool:
        """验证日期格式

        Args:
            date_str: 日期字符串

        Returns:
            bool: 是否有效
        """
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def _calculate_completeness(self, persons: List[Person]) -> float:
        """计算数据完整率

        Args:
            persons: 人物列表

        Returns:
            float: 完整率（0-1）
        """
        if not persons:
            return 0.0

        # 定义重要字段
        important_fields = [
            "name",
            "gender",
            "birth_date",
            "birth_place",
            "nationality",
            "summary",
        ]

        total_score = 0
        for person in persons:
            data = person.to_dict()
            field_count = sum(1 for field in important_fields if data.get(field))
            total_score += field_count / len(important_fields)

        return round(total_score / len(persons), 4)
