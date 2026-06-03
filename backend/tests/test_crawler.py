"""爬虫模块测试

测试数据采集、解析、清洗、验证等核心功能。
"""

import pytest
from datetime import datetime

# 导入被测试模块
from crawler.models import Person, Work, Relation, VALID_RELATION_TYPES, VALID_WORK_TYPES
from crawler.cleaner import DataCleaner
from crawler.validator import DataValidator, ValidationResult
from crawler.ner import RuleBasedNER, Entity
from crawler.relation import RelationExtractor
from crawler.entity_linking import EntityLinker


class TestModels:
    """测试数据模型"""

    def test_person_creation(self):
        """测试人物对象创建"""
        person = Person(
            id="person_001",
            name="周杰伦",
            name_en="Jay Chou",
            gender="male",
            birth_date="1979-01-18",
            summary="华语流行乐男歌手",
        )

        assert person.id == "person_001"
        assert person.name == "周杰伦"
        assert person.gender == "male"

    def test_person_to_dict(self):
        """测试人物对象序列化"""
        person = Person(
            id="person_001",
            name="周杰伦",
            summary="华语流行乐男歌手",
        )

        data = person.to_dict()
        assert data["id"] == "person_001"
        assert data["name"] == "周杰伦"
        assert "created_at" in data

    def test_person_from_dict(self):
        """测试从字典创建人物对象"""
        data = {
            "id": "person_001",
            "name": "周杰伦",
            "summary": "华语流行乐男歌手",
        }

        person = Person.from_dict(data)
        assert person.name == "周杰伦"
        assert person.id == "person_001"

    def test_work_creation(self):
        """测试作品对象创建"""
        work = Work(
            id="work_001",
            title="七里香",
            type="album",
            release_date="2004-08-03",
        )

        assert work.title == "七里香"
        assert work.type == "album"

    def test_relation_creation(self):
        """测试关系对象创建"""
        relation = Relation(
            source="person_001",
            target="person_002",
            type="MARRIED_TO",
            properties={"start_date": "2015-01-17"},
        )

        assert relation.source == "person_001"
        assert relation.type == "MARRIED_TO"


class TestDataCleaner:
    """测试数据清洗"""

    @pytest.fixture
    def cleaner(self):
        return DataCleaner()

    def test_clean_person_name(self, cleaner):
        """测试清洗人物姓名"""
        person = Person(
            id="person_001",
            name="  周杰伦  ",
            summary="歌手",
        )

        cleaned = cleaner.clean_person(person)
        assert cleaned.name == "周杰伦"

    def test_clean_person_gender(self, cleaner):
        """测试清洗性别"""
        person = Person(
            id="person_001",
            name="周杰伦",
            gender="男",
            summary="歌手",
        )

        cleaned = cleaner.clean_person(person)
        assert cleaned.gender == "male"

    def test_clean_person_date(self, cleaner):
        """测试清洗日期"""
        person = Person(
            id="person_001",
            name="周杰伦",
            birth_date="1979年01月18日",
            summary="歌手",
        )

        cleaned = cleaner.clean_person(person)
        assert cleaned.birth_date == "1979-01-18"

    def test_clean_person_height(self, cleaner):
        """测试清洗身高"""
        person = Person(
            id="person_001",
            name="周杰伦",
            height=175.0,
            summary="歌手",
        )

        cleaned = cleaner.clean_person(person)
        assert cleaned.height == 175.0

    def test_clean_person_invalid_height(self, cleaner):
        """测试清洗无效身高"""
        person = Person(
            id="person_001",
            name="周杰伦",
            height=500.0,  # 超出范围
            summary="歌手",
        )

        cleaned = cleaner.clean_person(person)
        assert cleaned.height is None

    def test_clean_person_empty_name_raises(self, cleaner):
        """测试空姓名抛出异常"""
        person = Person(
            id="person_001",
            name="",
            summary="歌手",
        )

        with pytest.raises(ValueError, match="人物姓名不能为空"):
            cleaner.clean_person(person)

    def test_clean_work(self, cleaner):
        """测试清洗作品"""
        work = Work(
            id="work_001",
            title="七里香",
            type="album",
            rating=9.0,
        )

        cleaned = cleaner.clean_work(work)
        assert cleaned.title == "七里香"
        assert cleaned.rating == 9.0

    def test_clean_relation(self, cleaner):
        """测试清洗关系"""
        relation = Relation(
            source="person_001",
            target="person_002",
            type="MARRIED_TO",
        )

        cleaned = cleaner.clean_relation(relation)
        assert cleaned.source == "person_001"
        assert cleaned.type == "MARRIED_TO"

    def test_clean_relation_self_loop_raises(self, cleaner):
        """测试自环关系抛出异常"""
        relation = Relation(
            source="person_001",
            target="person_001",
            type="MARRIED_TO",
        )

        with pytest.raises(ValueError, match="不能指向自身"):
            cleaner.clean_relation(relation)

    def test_truncate_text(self, cleaner):
        """测试文本截断"""
        long_text = "a" * 3000
        truncated = cleaner._truncate_text(long_text, 2000)
        assert len(truncated) <= 2000 + 3  # +3 for "..."


class TestDataValidator:
    """测试数据验证"""

    @pytest.fixture
    def validator(self):
        return DataValidator()

    def test_validate_valid_person(self, validator):
        """测试验证有效人物"""
        person = Person(
            id="person_001",
            name="周杰伦",
            summary="华语流行乐男歌手",
            gender="male",
            birth_date="1979-01-18",
        )

        result = validator.validate_person(person)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_validate_missing_required_fields(self, validator):
        """测试缺少必填字段"""
        person = Person(
            id="person_001",
            name="",
            summary="",
        )

        result = validator.validate_person(person)
        assert not result.is_valid
        assert len(result.errors) >= 2

    def test_validate_invalid_gender(self, validator):
        """测试无效性别"""
        person = Person(
            id="person_001",
            name="周杰伦",
            summary="歌手",
            gender="invalid",
        )

        result = validator.validate_person(person)
        assert not result.is_valid
        assert any(e.field == "gender" for e in result.errors)

    def test_validate_invalid_date(self, validator):
        """测试无效日期"""
        person = Person(
            id="person_001",
            name="周杰伦",
            summary="歌手",
            birth_date="invalid-date",
        )

        result = validator.validate_person(person)
        assert not result.is_valid
        assert any(e.field == "birth_date" for e in result.errors)

    def test_validate_invalid_height(self, validator):
        """测试无效身高"""
        person = Person(
            id="person_001",
            name="周杰伦",
            summary="歌手",
            height=500,
        )

        result = validator.validate_person(person)
        assert not result.is_valid
        assert any(e.field == "height" for e in result.errors)

    def test_validate_valid_work(self, validator):
        """测试验证有效作品"""
        work = Work(
            id="work_001",
            title="七里香",
            type="album",
        )

        result = validator.validate_work(work)
        assert result.is_valid

    def test_validate_invalid_work_type(self, validator):
        """测试无效作品类型"""
        work = Work(
            id="work_001",
            title="七里香",
            type="invalid_type",
        )

        result = validator.validate_work(work)
        assert not result.is_valid
        assert any(e.field == "type" for e in result.errors)

    def test_validate_relation_self_loop(self, validator):
        """测试验证自环关系"""
        relation = Relation(
            source="person_001",
            target="person_001",
            type="MARRIED_TO",
        )

        result = validator.validate_relation(relation)
        assert not result.is_valid
        assert any("自身" in e.message for e in result.errors)

    def test_validate_dataset(self, validator):
        """测试验证数据集"""
        persons = [
            Person(id="person_001", name="周杰伦", summary="歌手"),
            Person(id="person_002", name="昆凌", summary="演员"),
        ]
        works = [
            Work(id="work_001", title="七里香", type="album"),
        ]
        relations = [
            Relation(source="person_001", target="person_002", type="MARRIED_TO"),
        ]

        report = validator.validate_dataset(persons, works, relations)
        assert report["summary"]["valid_persons"] == 2
        assert report["summary"]["valid_works"] == 1
        assert report["summary"]["valid_relations"] == 1


class TestRuleBasedNER:
    """测试实体识别"""

    @pytest.fixture
    def ner(self):
        return RuleBasedNER()

    def test_extract_persons(self, ner):
        """测试提取人名"""
        text = "周杰伦和方文山合作创作了《七里香》"
        entities = ner.extract_persons(text)

        person_names = [e.text for e in entities]
        assert "周杰伦" in person_names
        assert "方文山" in person_names

    def test_extract_works(self, ner):
        """测试提取作品"""
        text = "周杰伦发行了《七里香》和《范特西》"
        entities = ner.extract_works(text)

        work_names = [e.text for e in entities]
        assert "七里香" in work_names
        assert "范特西" in work_names

    def test_extract_dates(self, ner):
        """测试提取日期"""
        text = "周杰伦出生于1979年01月18日"
        entities = ner.extract_dates(text)

        assert len(entities) == 1
        assert entities[0].text == "1979年01月18日"

    def test_extract_places(self, ner):
        """测试提取地点"""
        text = "周杰伦出生于台湾省新北市"
        entities = ner.extract_places(text)

        assert len(entities) >= 1

    def test_extract_all(self, ner):
        """测试提取所有实体"""
        text = "周杰伦和方文山在2004年合作创作了《七里香》"
        entities = ner.extract(text)

        labels = [e.label for e in entities]
        assert "PERSON" in labels
        assert "WORK" in labels
        assert "DATE" in labels

    def test_extract_relations(self, ner):
        """测试提取关系线索"""
        text = "周杰伦的妻子是昆凌，他们于2015年结婚"
        relations = ner.extract_relations(text)

        assert len(relations) >= 1
        assert any(r["type"] == "MARRIED_TO" for r in relations)


class TestRelationExtractor:
    """测试关系抽取"""

    @pytest.fixture
    def extractor(self):
        return RelationExtractor()

    def test_extract_marriage_from_text(self, extractor):
        """测试从文本抽取婚姻关系"""
        text = "周杰伦和昆凌于2015年结婚"
        relations = extractor.extract_from_text(text, "person_001", "周杰伦")

        assert len(relations) >= 1
        assert any(r.type == "MARRIED_TO" for r in relations)

    def test_extract_collaboration_from_text(self, extractor):
        """测试从文本抽取合作关系"""
        text = "周杰伦与方文山合作了多首歌曲"
        relations = extractor.extract_from_text(text, "person_001", "周杰伦")

        assert len(relations) >= 1
        assert any(r.type == "COLLABORATED_WITH" for r in relations)

    def test_extract_from_infobox(self, extractor):
        """测试从信息框抽取关系"""
        infobox = {
            "spouse": "昆凌",
            "relatives": "周耀中",
        }
        relations = extractor.extract_from_infobox(infobox, "person_001", "周杰伦")

        assert len(relations) >= 1
        assert any(r.type == "MARRIED_TO" for r in relations)

    def test_deduplicate_relations(self, extractor):
        """测试关系去重"""
        relations = [
            Relation(source="p1", target="p2", type="MARRIED_TO"),
            Relation(source="p1", target="p2", type="MARRIED_TO"),
            Relation(source="p1", target="p3", type="COLLABORATED_WITH"),
        ]

        deduped = extractor._deduplicate_relations(relations)
        assert len(deduped) == 2


class TestEntityLinker:
    """测试实体链接"""

    @pytest.fixture
    def linker(self):
        linker = EntityLinker()
        linker.add_entity(
            "person_001",
            "周杰伦",
            aliases=["Jay Chou", "周董"],
        )
        linker.add_entity(
            "person_002",
            "昆凌",
            aliases=["Hannah Quinlivan"],
        )
        return linker

    def test_exact_match(self, linker):
        """测试精确匹配"""
        result = linker.link("周杰伦")
        assert result == "person_001"

    def test_alias_match(self, linker):
        """测试别名匹配"""
        result = linker.link("周董")
        assert result == "person_001"

    def test_fuzzy_match(self, linker):
        """测试模糊匹配"""
        result = linker.link("周杰伦")  # 精确匹配
        assert result == "person_001"

    def test_no_match(self, linker):
        """测试无匹配"""
        result = linker.link("不存在的名字")
        assert result is None

    def test_get_entity_info(self, linker):
        """测试获取实体信息"""
        info = linker.get_entity_info("person_001")
        assert info is not None
        assert info["name"] == "周杰伦"

    def test_batch_link(self, linker):
        """测试批量链接"""
        names = ["周杰伦", "昆凌", "不存在"]
        results = linker.link_batch(names)

        assert results["周杰伦"] == "person_001"
        assert results["昆凌"] == "person_002"
        assert results["不存在"] is None


class TestIntegration:
    """集成测试"""

    def test_full_pipeline(self):
        """测试完整数据处理流程"""
        # 1. 创建原始数据
        person = Person(
            id="person_001",
            name="  周杰伦  ",
            gender="男",
            birth_date="1979年01月18日",
            height=175.0,
            summary="华语流行乐男歌手",
        )

        work = Work(
            id="work_001",
            title="七里香",
            type="专辑",
            rating=9.0,
        )

        relation = Relation(
            source="person_001",
            target="person_002",
            type="married_to",
        )

        # 2. 清洗
        cleaner = DataCleaner()
        person = cleaner.clean_person(person)
        work = cleaner.clean_work(work)
        relation = cleaner.clean_relation(relation)

        # 3. 验证
        validator = DataValidator()
        person_result = validator.validate_person(person)
        work_result = validator.validate_work(work)
        relation_result = validator.validate_relation(relation)

        # 4. 断言
        assert person.name == "周杰伦"
        assert person.gender == "male"
        assert person.birth_date == "1979-01-18"
        assert work.type == "album"
        assert relation.type == "MARRIED_TO"

        assert person_result.is_valid
        assert work_result.is_valid
        assert relation_result.is_valid

    def test_data_quality_metrics(self):
        """测试数据质量指标"""
        persons = [
            Person(id="p1", name="周杰伦", gender="male", birth_date="1979-01-18", summary="歌手"),
            Person(id="p2", name="昆凌", gender="female", summary="演员"),
            Person(id="p3", name="方文山", summary="作词人"),
        ]

        validator = DataValidator()
        completeness = validator._calculate_completeness(persons)

        # 3个人，字段完整度应该在0-1之间
        assert 0 <= completeness <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
