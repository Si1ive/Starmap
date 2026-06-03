"""实体链接模块

将抽取的实体名称链接到知识图谱中的标准实体ID。
支持精确匹配、模糊匹配和基于上下文的重名消歧。
"""

import re
import logging
from typing import Optional, Dict, Any, List, Tuple
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class EntityLinker:
    """实体链接器

    将文本中的实体名称映射到知识图谱中的标准实体ID。

    使用示例:
        >>> linker = EntityLinker()
        >>> linker.add_entity("person_001", "周杰伦", aliases=["Jay Chou", "周董"])
        >>> entity_id = linker.link("周董")
        >>> print(entity_id)
        'person_001'
    """

    # 相似度阈值
    EXACT_MATCH_THRESHOLD = 1.0
    HIGH_CONFIDENCE_THRESHOLD = 0.9
    MEDIUM_CONFIDENCE_THRESHOLD = 0.7
    LOW_CONFIDENCE_THRESHOLD = 0.5

    def __init__(self):
        """初始化实体链接器"""
        # 实体名称到ID的映射
        self._name_to_id: Dict[str, str] = {}
        # ID到实体信息的映射
        self._id_to_info: Dict[str, Dict[str, Any]] = {}
        # 别名映射
        self._alias_to_id: Dict[str, str] = {}

        logger.info("EntityLinker initialized")

    def add_entity(
        self,
        entity_id: str,
        name: str,
        entity_type: str = "person",
        aliases: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None,
    ):
        """添加实体到链接器

        Args:
            entity_id: 实体唯一ID
            name: 实体标准名称
            entity_type: 实体类型（person/work/company等）
            aliases: 别名列表
            properties: 额外属性（用于消歧）
        """
        # 存储实体信息
        self._id_to_info[entity_id] = {
            "id": entity_id,
            "name": name,
            "type": entity_type,
            "aliases": aliases or [],
            "properties": properties or {},
        }

        # 建立名称映射
        self._name_to_id[name] = entity_id

        # 建立别名映射
        if aliases:
            for alias in aliases:
                alias = alias.strip()
                if alias and alias != name:
                    self._alias_to_id[alias] = entity_id

        logger.debug(f"Added entity: {entity_id} -> {name}")

    def add_entities(self, entities: List[Dict[str, Any]]):
        """批量添加实体

        Args:
            entities: 实体列表，每个实体是一个字典
        """
        for entity in entities:
            self.add_entity(
                entity_id=entity["id"],
                name=entity["name"],
                entity_type=entity.get("type", "person"),
                aliases=entity.get("aliases"),
                properties=entity.get("properties"),
            )

    def link(self, name: str, context: Optional[str] = None) -> Optional[str]:
        """链接实体名称到ID

        按以下优先级尝试匹配：
        1. 精确匹配标准名称
        2. 精确匹配别名
        3. 模糊匹配（编辑距离）
        4. 基于上下文的消歧（如果有重名）

        Args:
            name: 实体名称
            context: 上下文文本（用于消歧）

        Returns:
            Optional[str]: 实体ID，未找到则返回None
        """
        if not name:
            return None

        name = name.strip()

        # 1. 精确匹配标准名称
        if name in self._name_to_id:
            return self._name_to_id[name]

        # 2. 精确匹配别名
        if name in self._alias_to_id:
            return self._alias_to_id[name]

        # 3. 模糊匹配
        candidates = self._fuzzy_match(name)
        if not candidates:
            return None

        # 4. 如果有多个候选，尝试消歧
        if len(candidates) == 1:
            return candidates[0][0]

        # 有多个候选，需要消歧
        if context:
            return self._disambiguate(name, candidates, context)

        # 无法消歧，返回置信度最高的
        return candidates[0][0]

    def link_batch(self, names: List[str], contexts: Optional[List[str]] = None) -> Dict[str, Optional[str]]:
        """批量链接实体

        Args:
            names: 实体名称列表
            contexts: 对应的上下文列表

        Returns:
            Dict[str, Optional[str]]: 名称到ID的映射
        """
        results = {}
        for i, name in enumerate(names):
            context = contexts[i] if contexts and i < len(contexts) else None
            results[name] = self.link(name, context)

        return results

    def _fuzzy_match(self, name: str) -> List[Tuple[str, float]]:
        """模糊匹配

        使用编辑距离计算相似度。

        Args:
            name: 查询名称

        Returns:
            List[Tuple[str, float]]: (实体ID, 相似度) 列表，按相似度降序
        """
        candidates = []

        # 检查所有标准名称
        for std_name, entity_id in self._name_to_id.items():
            similarity = self._calculate_similarity(name, std_name)
            if similarity >= self.LOW_CONFIDENCE_THRESHOLD:
                candidates.append((entity_id, similarity))

        # 检查所有别名
        for alias, entity_id in self._alias_to_id.items():
            similarity = self._calculate_similarity(name, alias)
            if similarity >= self.LOW_CONFIDENCE_THRESHOLD:
                candidates.append((entity_id, similarity))

        # 去重并排序
        seen = set()
        unique_candidates = []
        for entity_id, similarity in sorted(candidates, key=lambda x: -x[1]):
            if entity_id not in seen:
                seen.add(entity_id)
                unique_candidates.append((entity_id, similarity))

        return unique_candidates

    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """计算两个字符串的相似度

        使用SequenceMatcher计算编辑距离相似度。

        Args:
            s1: 字符串1
            s2: 字符串2

        Returns:
            float: 相似度（0-1）
        """
        return SequenceMatcher(None, s1, s2).ratio()

    def _disambiguate(
        self,
        name: str,
        candidates: List[Tuple[str, float]],
        context: str,
    ) -> Optional[str]:
        """实体消歧

        基于上下文信息选择最匹配的实体。

        Args:
            name: 实体名称
            candidates: 候选实体列表
            context: 上下文文本

        Returns:
            Optional[str]: 最匹配的实体ID
        """
        best_match = None
        best_score = 0

        for entity_id, base_similarity in candidates:
            entity_info = self._id_to_info.get(entity_id)
            if not entity_info:
                continue

            # 计算上下文匹配分数
            context_score = self._calculate_context_score(entity_info, context)

            # 综合分数
            total_score = base_similarity * 0.6 + context_score * 0.4

            if total_score > best_score:
                best_score = total_score
                best_match = entity_id

        return best_match

    def _calculate_context_score(
        self, entity_info: Dict[str, Any], context: str
    ) -> float:
        """计算上下文匹配分数

        检查上下文中是否出现与实体相关的关键词。

        Args:
            entity_info: 实体信息
            context: 上下文文本

        Returns:
            float: 匹配分数（0-1）
        """
        score = 0.0
        context_lower = context.lower()

        # 检查别名是否出现在上下文中
        aliases = entity_info.get("aliases", [])
        for alias in aliases:
            if alias.lower() in context_lower:
                score += 0.3

        # 检查属性关键词
        properties = entity_info.get("properties", {})
        for key, value in properties.items():
            if isinstance(value, str) and value.lower() in context_lower:
                score += 0.2

        # 检查类型相关词
        entity_type = entity_info.get("type", "")
        type_keywords = {
            "person": ["歌手", "演员", "导演", "艺人", "明星", "音乐家"],
            "work": ["专辑", "电影", "电视剧", "歌曲", "作品"],
            "company": ["公司", "集团", "娱乐", "唱片", "影业"],
        }
        for keyword in type_keywords.get(entity_type, []):
            if keyword in context:
                score += 0.1

        return min(score, 1.0)

    def get_entity_info(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """获取实体信息

        Args:
            entity_id: 实体ID

        Returns:
            Optional[Dict]: 实体信息
        """
        return self._id_to_info.get(entity_id)

    def get_entity_name(self, entity_id: str) -> Optional[str]:
        """获取实体名称

        Args:
            entity_id: 实体ID

        Returns:
            Optional[str]: 实体名称
        """
        info = self._id_to_info.get(entity_id)
        return info["name"] if info else None

    def remove_entity(self, entity_id: str):
        """移除实体

        Args:
            entity_id: 实体ID
        """
        if entity_id not in self._id_to_info:
            return

        entity_info = self._id_to_info[entity_id]
        name = entity_info["name"]
        aliases = entity_info.get("aliases", [])

        # 移除映射
        if name in self._name_to_id and self._name_to_id[name] == entity_id:
            del self._name_to_id[name]

        for alias in aliases:
            if alias in self._alias_to_id and self._alias_to_id[alias] == entity_id:
                del self._alias_to_id[alias]

        del self._id_to_info[entity_id]

        logger.info(f"Removed entity: {entity_id}")

    def get_all_entities(self) -> List[Dict[str, Any]]:
        """获取所有实体

        Returns:
            List[Dict]: 所有实体信息列表
        """
        return list(self._id_to_info.values())

    def get_entity_count(self) -> int:
        """获取实体数量

        Returns:
            int: 实体数量
        """
        return len(self._id_to_info)

    def clear(self):
        """清空所有实体"""
        self._name_to_id.clear()
        self._id_to_info.clear()
        self._alias_to_id.clear()
        logger.info("EntityLinker cleared")
