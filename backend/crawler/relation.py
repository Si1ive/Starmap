"""关系抽取模块

从文本和结构化数据中提取人物关系。
支持基于规则的关系抽取。
"""

import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from .models import Relation, Person
from .ner import RuleBasedNER

logger = logging.getLogger(__name__)


@dataclass
class RelationExtractionResult:
    """关系抽取结果"""

    relations: List[Relation]
    confidence: float
    source_text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relations": [r.to_dict() for r in self.relations],
            "confidence": self.confidence,
            "source_text": self.source_text,
        }


class RelationExtractor:
    """关系抽取器

    从文本中抽取人物之间的关系。

    使用示例:
        >>> extractor = RelationExtractor()
        >>> relations = extractor.extract_from_text(
        ...     "周杰伦和昆凌于2015年结婚",
        ...     "person_001",
        ...     "周杰伦"
        ... )
    """

    # 关系模式定义
    RELATION_PATTERNS = {
        "MARRIED_TO": {
            "patterns": [
                r"(\S{2,4})(?:的)?(?:妻子|丈夫|配偶|老婆|老公)",
                r"(?:与|和)(\S{2,4})(?:于|在)?(?:\d{4}年)?(?:结婚|成婚|结为夫妻|登记结婚)",
                r"(?:嫁给|娶了|迎娶)(\S{2,4})",
                r"(\S{2,4})(?:与|和)(\S{2,4})(?:的)?(?:婚姻|婚礼)",
            ],
            "confidence": 0.8,
        },
        "COLLABORATED_WITH": {
            "patterns": [
                r"(?:与|和)(\S{2,4})(?:合作|搭档|搭档演出|共同创作|合唱|合演)",
                r"(\S{2,4})(?:与|和)(\S{2,4})(?:合作|搭档)",
                r"(?:联手|联袂|携手)(\S{2,4})",
                r"(\S{2,4})(?:作词|作曲|编曲|制作|导演).*?(?:由|为)(\S{2,4})",
            ],
            "confidence": 0.7,
        },
        "MENTOR_OF": {
            "patterns": [
                r"(?:师从|拜师|受教于|受业于)(\S{2,4})",
                r"(\S{2,4})(?:的)?(?:老师|师父|导师|师傅|恩师)",
                r"(?:学生|徒弟|弟子|门生)(\S{2,4})",
                r"(\S{2,4})(?:指导|教导|培养|提携)(\S{2,4})",
            ],
            "confidence": 0.7,
        },
        "RELATIVE": {
            "patterns": [
                r"(?:父亲|爸爸|爹)(\S{2,4})",
                r"(?:母亲|妈妈|娘)(\S{2,4})",
                r"(?:哥哥|弟弟|兄长|兄弟)(\S{2,4})",
                r"(?:姐姐|妹妹|姊姊|姐妹)(\S{2,4})",
                r"(?:儿子|女儿|子女|孩子)(\S{2,4})",
                r"(?:祖父|爷爷|外祖父|姥爷)(\S{2,4})",
                r"(?:祖母|奶奶|外祖母|姥姥)(\S{2,4})",
                r"(?:叔叔|伯伯|舅舅|姑姑|姨妈)(\S{2,4})",
                r"(\S{2,4})(?:的)?(?:父亲|母亲|哥哥|弟弟|姐姐|妹妹|儿子|女儿)",
            ],
            "confidence": 0.6,
            "properties_map": {
                "父亲": "parent",
                "爸爸": "parent",
                "爹": "parent",
                "母亲": "parent",
                "妈妈": "parent",
                "娘": "parent",
                "哥哥": "sibling",
                "弟弟": "sibling",
                "兄长": "sibling",
                "兄弟": "sibling",
                "姐姐": "sibling",
                "妹妹": "sibling",
                "姊姊": "sibling",
                "姐妹": "sibling",
                "儿子": "child",
                "女儿": "child",
                "子女": "child",
                "孩子": "child",
                "祖父": "grandparent",
                "爷爷": "grandparent",
                "外祖父": "grandparent",
                "姥爷": "grandparent",
                "祖母": "grandparent",
                "奶奶": "grandparent",
                "外祖母": "grandparent",
                "姥姥": "grandparent",
            },
        },
        "WORKS_FOR": {
            "patterns": [
                r"(?:加入|签约|加盟|效力于)(\S+?)(?:公司|集团|娱乐|唱片|影业|工作室)",
                r"(\S+?)(?:公司|集团|娱乐|唱片|影业|工作室)(?:的)?(?:艺人|歌手|演员)",
            ],
            "confidence": 0.6,
        },
    }

    def __init__(self):
        """初始化关系抽取器"""
        self.ner = RuleBasedNER()
        logger.info("RelationExtractor initialized")

    def extract_from_text(
        self,
        text: str,
        person_id: str,
        person_name: str,
    ) -> List[Relation]:
        """从文本中抽取关系

        Args:
            text: 输入文本
            person_id: 当前人物ID
            person_name: 当前人物名称

        Returns:
            List[Relation]: 抽取的关系列表
        """
        relations = []

        for relation_type, config in self.RELATION_PATTERNS.items():
            for pattern in config["patterns"]:
                for match in re.finditer(pattern, text):
                    groups = match.groups()

                    if len(groups) >= 2:
                        # 模式中有两个人名
                        if groups[0] == person_name:
                            target = groups[1]
                        elif groups[1] == person_name:
                            target = groups[0]
                        else:
                            # 都不匹配当前人物，尝试将第一个捕获组作为目标
                            # 适用于"与XXX结婚"这样的模式
                            target = groups[0]
                    else:
                        target = groups[0]

                    # 排除自身
                    if target == person_name:
                        continue

                    # 构建属性
                    properties = {}
                    if "properties_map" in config:
                        matched_text = match.group(0)
                        for keyword, prop_value in config["properties_map"].items():
                            if keyword in matched_text:
                                properties["type"] = prop_value
                                break

                    relation = Relation(
                        source=person_id,
                        target=target,  # 注意：这里存储的是名称，需要后续实体链接
                        type=relation_type,
                        properties=properties,
                    )

                    relations.append(relation)

        # 去重
        relations = self._deduplicate_relations(relations)

        logger.info(
            f"Extracted {len(relations)} relations from text for {person_name}"
        )
        return relations

    def extract_from_infobox(
        self,
        infobox_data: Dict[str, Any],
        person_id: str,
        person_name: str,
    ) -> List[Relation]:
        """从信息框数据中抽取关系

        Args:
            infobox_data: 信息框数据
            person_id: 当前人物ID
            person_name: 当前人物名称

        Returns:
            List[Relation]: 抽取的关系列表
        """
        relations = []

        # 配偶关系
        if infobox_data.get("spouse"):
            spouse_names = self._parse_name_list(infobox_data["spouse"])
            for spouse_name in spouse_names:
                if spouse_name and spouse_name != person_name:
                    relations.append(
                        Relation(
                            source=person_id,
                            target=spouse_name,
                            type="MARRIED_TO",
                        )
                    )

        # 亲属关系
        if infobox_data.get("relatives"):
            relative_names = self._parse_name_list(infobox_data["relatives"])
            for relative_name in relative_names:
                if relative_name and relative_name != person_name:
                    relations.append(
                        Relation(
                            source=person_id,
                            target=relative_name,
                            type="RELATIVE",
                            properties={"type": "relative"},
                        )
                    )

        # 子女关系
        if infobox_data.get("children"):
            children_names = self._parse_name_list(infobox_data["children"])
            for child_name in children_names:
                if child_name and child_name != person_name:
                    relations.append(
                        Relation(
                            source=person_id,
                            target=child_name,
                            type="RELATIVE",
                            properties={"type": "child"},
                        )
                    )

        # 公司关系
        if infobox_data.get("record_label"):
            companies = self._parse_name_list(infobox_data["record_label"])
            for company in companies:
                if company:
                    relations.append(
                        Relation(
                            source=person_id,
                            target=company,
                            type="SIGNED_WITH",
                            properties={"company_type": "record"},
                        )
                    )

        if infobox_data.get("agency"):
            agencies = self._parse_name_list(infobox_data["agency"])
            for agency in agencies:
                if agency:
                    relations.append(
                        Relation(
                            source=person_id,
                            target=agency,
                            type="WORKS_FOR",
                            properties={"company_type": "agency"},
                        )
                    )

        logger.info(
            f"Extracted {len(relations)} relations from infobox for {person_name}"
        )
        return relations

    def extract_collaborations(
        self,
        works: List[Dict[str, Any]],
        person_id: str,
        person_name: str,
    ) -> List[Relation]:
        """从作品信息中抽取合作关系

        如果多个艺人出现在同一作品中，认为他们存在合作关系。

        Args:
            works: 作品列表（包含参与人员信息）
            person_id: 当前人物ID
            person_name: 当前人物名称

        Returns:
            List[Relation]: 合作关系列表
        """
        relations = []
        collaborators = set()

        for work in works:
            # 检查作品中是否有其他艺人
            participants = work.get("participants", [])
            for participant in participants:
                if participant != person_name:
                    collaborators.add(participant)

        for collaborator in collaborators:
            relations.append(
                Relation(
                    source=person_id,
                    target=collaborator,
                    type="COLLABORATED_WITH",
                )
            )

        logger.info(
            f"Extracted {len(relations)} collaboration relations for {person_name}"
        )
        return relations

    def _parse_name_list(self, text: str) -> List[str]:
        """解析名称列表

        Args:
            text: 包含多个名称的文本

        Returns:
            List[str]: 名称列表
        """
        if not text:
            return []

        # 使用多种分隔符分割
        names = re.split(r"[,，、;/]", text)
        # 清理并过滤
        names = [name.strip() for name in names if name.strip()]
        # 移除括号内的内容
        names = [re.sub(r"[（(].*?[)）]", "", name).strip() for name in names]
        # 过滤过短的
        names = [name for name in names if len(name) >= 2]

        return names

    def _deduplicate_relations(self, relations: List[Relation]) -> List[Relation]:
        """去重关系

        Args:
            relations: 关系列表

        Returns:
            List[Relation]: 去重后的关系列表
        """
        seen = set()
        deduped = []

        for relation in relations:
            key = (relation.source, relation.target, relation.type)
            if key not in seen:
                seen.add(key)
                deduped.append(relation)

        return deduped

    def filter_relations_by_confidence(
        self,
        relations: List[Relation],
        min_confidence: float = 0.5,
    ) -> List[Relation]:
        """按置信度过滤关系

        Args:
            relations: 关系列表
            min_confidence: 最小置信度

        Returns:
            List[Relation]: 过滤后的关系列表
        """
        # 这里可以根据关系类型设置不同的置信度阈值
        filtered = []
        for relation in relations:
            confidence = self.RELATION_PATTERNS.get(relation.type, {}).get(
                "confidence", 0.5
            )
            if confidence >= min_confidence:
                filtered.append(relation)

        return filtered
