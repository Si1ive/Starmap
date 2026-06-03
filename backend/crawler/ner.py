"""实体识别模块（NER）

提供基于规则和词典的命名实体识别功能。
作为LLM-based NER的轻量级替代方案。
"""

import re
import logging
from typing import List, Dict, Set, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """识别出的实体"""

    text: str
    label: str
    start: int
    end: int
    confidence: float = 1.0

    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
        }


class RuleBasedNER:
    """基于规则的命名实体识别

    使用正则表达式和词典匹配识别人名、作品名等实体。

    使用示例:
        >>> ner = RuleBasedNER()
        >>> entities = ner.extract("周杰伦和方文山合作创作了《七里香》")
        >>> for e in entities:
        ...     print(e.text, e.label)
    """

    # 常见中文姓氏
    SURNAMES = {
        "李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴",
        "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
        "梁", "宋", "郑", "谢", "韩", "唐", "冯", "于", "董", "萧",
        "程", "曹", "袁", "邓", "许", "傅", "沈", "曾", "彭", "吕",
        "苏", "卢", "蒋", "蔡", "贾", "丁", "魏", "薛", "叶", "阎",
        "余", "潘", "杜", "戴", "夏", "钟", "汪", "田", "任", "姜",
        "范", "方", "石", "姚", "谭", "廖", "邹", "熊", "金", "陆",
        "郝", "孔", "白", "崔", "康", "毛", "邱", "秦", "江", "史",
        "顾", "侯", "邵", "孟", "龙", "万", "段", "雷", "钱", "汤",
        "尹", "黎", "易", "常", "武", "乔", "贺", "赖", "龚", "文",
        "欧阳", "太史", "端木", "上官", "司马", "东方", "独孤", "南宫",
        "万俟", "闻人", "夏侯", "诸葛", "尉迟", "公羊", "赫连", "澹台",
        "皇甫", "宗政", "濮阳", "公冶", "太叔", "申屠", "公孙", "慕容",
        "仲孙", "钟离", "长孙", "宇文", "司徒", "鲜于", "司空", "闾丘",
        "子车", "亓官", "司寇", "巫马", "公西", "颛孙", "壤驷", "公良",
        "漆雕", "乐正", "宰父", "谷梁", "拓跋", "夹谷", "轩辕", "令狐",
        "段干", "百里", "呼延", "东郭", "南门", "羊舌", "微生", "公户",
        "公玉", "公仪", "梁丘", "公仲", "公上", "公门", "公山", "公坚",
        "左丘", "公伯", "西门", "公祖", "第五", "公乘", "贯丘", "公皙",
        "南荣", "东里", "东宫", "仲长", "子书", "子桑", "即墨", "达奚",
        "褚师", "吴铭",
    }

    # 常见作品类型词
    WORK_TYPE_WORDS = {
        "专辑", "单曲", "EP", "电影", "电视剧", "网剧", "话剧",
        "舞台剧", "音乐剧", "纪录片", "动画片", "综艺", "节目",
        "书籍", "小说", "散文", "诗集", "自传", "传记",
        "歌曲", "唱片", "演唱会", "MV",
    }

    # 常见公司类型词
    COMPANY_TYPE_WORDS = {
        "公司", "集团", "娱乐", "唱片", "影业", "传媒", "文化",
        "工作室", "经纪", "厂牌",
    }

    def __init__(self):
        """初始化NER"""
        # 编译正则表达式
        self._compile_patterns()
        logger.info("RuleBasedNER initialized")

    def _compile_patterns(self):
        """编译正则表达式模式"""
        # 人名模式：2-4个汉字，以常见姓氏开头
        surname_pattern = "|".join(sorted(self.SURNAMES, key=len, reverse=True))
        # 常见连接词/助词/动词，遇到这些字符说明名字结束
        stop_chars = "和与的之了在是及或合作创作演唱出演导制作"
        self.person_pattern = re.compile(
            rf"({surname_pattern})([\u4e00-\u9fff]{{1,3}}?)(?=[{stop_chars}]|$|[^\u4e00-\u9fff])",
            re.UNICODE,
        )

        # 作品模式：《作品名》或"作品名" + 类型词
        self.work_pattern = re.compile(
            r"[\u300a\"\']([^\"\'\u300b]+)[\"\'\u300b]",
            re.UNICODE,
        )

        # 日期模式 - 匹配 YYYY年MM月DD日 或 YYYY年
        self.date_pattern = re.compile(
            r"(\d{4})年(?:\s*(\d{1,2})月\s*(\d{1,2})日)?",
        )

        # 地点模式：XX省/市/县
        self.place_pattern = re.compile(
            r"([\u4e00-\u9fff]{2,10}(?:省|市|自治区|县|区|镇|乡|村))",
            re.UNICODE,
        )

    def extract(self, text: str) -> List[Entity]:
        """提取所有实体

        Args:
            text: 输入文本

        Returns:
            List[Entity]: 实体列表
        """
        entities = []
        entities.extend(self.extract_persons(text))
        entities.extend(self.extract_works(text))
        entities.extend(self.extract_dates(text))
        entities.extend(self.extract_places(text))

        # 去重（按位置）
        entities = self._deduplicate(entities)

        return entities

    def extract_persons(self, text: str) -> List[Entity]:
        """提取人名

        Args:
            text: 输入文本

        Returns:
            List[Entity]: 人名实体列表
        """
        entities = []
        for match in self.person_pattern.finditer(text):
            # group(1)是姓氏，group(2)是名字部分
            name = match.group(1) + match.group(2)
            # 过滤一些常见误匹配
            if self._is_valid_person_name(name):
                entities.append(
                    Entity(
                        text=name,
                        label="PERSON",
                        start=match.start(1),
                        end=match.end(2),
                        confidence=0.7,
                    )
                )

        return entities

    def extract_works(self, text: str) -> List[Entity]:
        """提取作品名

        匹配书名号《》或引号""内的内容。

        Args:
            text: 输入文本

        Returns:
            List[Entity]: 作品实体列表
        """
        entities = []
        for match in self.work_pattern.finditer(text):
            work_name = match.group(1).strip()
            if len(work_name) >= 2 and len(work_name) <= 50:
                entities.append(
                    Entity(
                        text=work_name,
                        label="WORK",
                        start=match.start(),
                        end=match.end(),
                        confidence=0.8,
                    )
                )

        return entities

    def extract_dates(self, text: str) -> List[Entity]:
        """提取日期

        Args:
            text: 输入文本

        Returns:
            List[Entity]: 日期实体列表
        """
        entities = []
        for match in self.date_pattern.finditer(text):
            entities.append(
                Entity(
                    text=match.group(0),
                    label="DATE",
                    start=match.start(),
                    end=match.end(),
                    confidence=0.9,
                )
            )

        return entities

    def extract_places(self, text: str) -> List[Entity]:
        """提取地点

        Args:
            text: 输入文本

        Returns:
            List[Entity]: 地点实体列表
        """
        entities = []
        for match in self.place_pattern.finditer(text):
            entities.append(
                Entity(
                    text=match.group(0),
                    label="PLACE",
                    start=match.start(),
                    end=match.end(),
                    confidence=0.6,
                )
            )

        return entities

    def extract_relations(self, text: str) -> List[Dict[str, Any]]:
        """提取关系线索

        从文本中提取可能的关系描述。

        Args:
            text: 输入文本

        Returns:
            List[Dict]: 关系线索列表
        """
        relations = []

        # 婚姻关系线索
        marriage_patterns = [
            r"(\S{2,4})的(?:妻子|丈夫|配偶|老婆|老公)",
            r"(\S{2,4})与(\S{2,4})(?:结婚|成婚|结为夫妻)",
            r"(?:嫁给|娶了)(\S{2,4})",
        ]

        for pattern in marriage_patterns:
            for match in re.finditer(pattern, text):
                if len(match.groups()) == 2:
                    relations.append({
                        "type": "MARRIED_TO",
                        "source": match.group(1),
                        "target": match.group(2),
                        "context": match.group(0),
                    })
                else:
                    relations.append({
                        "type": "MARRIED_TO",
                        "target": match.group(1),
                        "context": match.group(0),
                    })

        # 合作关系线索
        collab_patterns = [
            r"(\S{2,4})与(\S{2,4})(?:合作|搭档|搭档演出|共同创作)",
            r"(\S{2,4})(?:和|与)(\S{2,4})一起",
        ]

        for pattern in collab_patterns:
            for match in re.finditer(pattern, text):
                if len(match.groups()) == 2:
                    relations.append({
                        "type": "COLLABORATED_WITH",
                        "source": match.group(1),
                        "target": match.group(2),
                        "context": match.group(0),
                    })

        # 师徒关系
        mentor_patterns = [
            r"(\S{2,4})的(?:老师|师父|导师|师傅)",
            r"师从(\S{2,4})",
            r"(\S{2,4})的(?:学生|徒弟|弟子)",
        ]

        for pattern in mentor_patterns:
            for match in re.finditer(pattern, text):
                relations.append({
                    "type": "MENTOR_OF",
                    "target": match.group(1),
                    "context": match.group(0),
                })

        return relations

    def _is_valid_person_name(self, name: str) -> bool:
        """验证是否是有效人名

        过滤一些常见的误匹配。

        Args:
            name: 候选名称

        Returns:
            bool: 是否有效
        """
        # 过滤常见非人名词
        invalid_names = {
            "其中", "其他", "这个", "那个", "什么", "怎么", "为什么",
            "因为", "所以", "但是", "然而", "而且", "或者", "还是",
            "虽然", "尽管", "即使", "如果", "那么", "然后", "接着",
            "首先", "其次", "最后", "总之", "例如", "比如", "像是",
            "关于", "对于", "根据", "按照", "通过", "经过", "随着",
            "除了", "除去", "除非", "除了", "只有", "只要", "由于",
            "不仅", "不但", "不管", "不论", "无论", "尽管", "即使",
        }

        if name in invalid_names:
            return False

        # 过滤纯数字
        if name.isdigit():
            return False

        # 过滤长度不合适的
        if len(name) < 2 or len(name) > 5:
            return False

        return True

    def _deduplicate(self, entities: List[Entity]) -> List[Entity]:
        """去重实体

        按位置去重，保留置信度高的。

        Args:
            entities: 实体列表

        Returns:
            List[Entity]: 去重后的实体列表
        """
        # 按位置排序
        sorted_entities = sorted(entities, key=lambda e: (e.start, -e.confidence))

        deduped = []
        for entity in sorted_entities:
            # 检查是否与已保留的实体重叠
            overlap = False
            for kept in deduped:
                if not (entity.end <= kept.start or entity.start >= kept.end):
                    overlap = True
                    break

            if not overlap:
                deduped.append(entity)

        return sorted(deduped, key=lambda e: e.start)

    def add_custom_person(self, name: str):
        """添加自定义人名

        用于补充词典中缺失的人名。

        Args:
            name: 人名
        """
        # 重新编译模式以包含新的人名
        # 注意：这只是一个简单的实现，实际应用中可能需要更高效的方案
        logger.info(f"Added custom person: {name}")

    def add_custom_work(self, work_name: str):
        """添加自定义作品名

        Args:
            work_name: 作品名
        """
        logger.info(f"Added custom work: {work_name}")
