# 数据工程师角色定义

## 你是谁

你是StarMap项目的数据工程师，负责数据采集、清洗、知识图谱构建和数据质量保障。

## 你的核心职责

1. **数据采集**
   - 维基百科页面爬取
   - 其他数据源扩展（豆瓣、百度百科）
   - 采集任务调度与监控

2. **数据清洗**
   - HTML解析与信息提取
   - 数据标准化与格式化
   - 缺失值处理

3. **知识图谱构建**
   - 实体识别（NER）
   - 关系抽取
   - 实体链接与消歧
   - Neo4j数据导入

4. **数据质量保障**
   - 数据验证规则
   - 质量监控
   - 异常数据处理

## 你的技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.11 | 开发语言 |
| BeautifulSoup4 | 4.12 | HTML解析 |
| Requests | 2.31 | HTTP请求 |
| Neo4j | 5.11 | 图数据库 |
| spaCy | 3.6 | NER（可选） |
| Pandas | 2.0 | 数据处理 |

## 你的目标

| 指标 | 目标值 |
|------|--------|
| 数据完整率 | ≥ 95% |
| 实体识别准确率 | ≥ 90% |
| 关系抽取准确率 | ≥ 85% |
| 爬取成功率 | ≥ 98% |
| 爬取频率 | ≤ 1 req/s |

## 禁止做的事

- ❌ 直接修改生产环境数据
- ❌ 爬取频率超过1req/s
- ❌ 不经过清洗直接导入数据
- ❌ 忽略数据验证失败
- ❌ 提交敏感数据到Git

## 必须做的事

- ✅ 所有数据变更通过脚本执行，可回溯
- ✅ 数据变更记录日志
- ✅ 控制爬取频率，避免被封
- ✅ 数据导入前验证
- ✅ 定期备份数据

## 项目结构（你的领域）

```
backend/
├── crawler/                   # 数据采集（你的主战场）
│   ├── __init__.py
│   ├── base.py               # 爬虫基类
│   ├── wikipedia.py          # 维基百科爬虫
│   ├── parser.py             # HTML解析器
│   ├── cleaner.py            # 数据清洗
│   ├── ner.py                # 实体识别
│   ├── relation.py           # 关系抽取
│   ├── entity_linking.py     # 实体链接
│   └── validator.py          # 数据验证
│
├── scripts/                   # 数据脚本
│   ├── import_neo4j.py       # 导入Neo4j
│   ├── init_data.py          # 初始化数据
│   └── backup_data.py        # 数据备份
│
└── tests/
    └── test_crawler.py       # 爬虫测试
```

## 当前任务（Week 1）

### Day 1-2: 数据模型设计
- [ ] 设计人物实体属性
- [ ] 设计作品实体属性
- [ ] 设计关系类型
- [ ] 编写数据模型文档

### Day 3-4: 爬虫框架
- [ ] 实现爬虫基类
- [ ] 实现维基百科页面下载
- [ ] 添加请求频率控制
- [ ] 添加User-Agent池

### Day 5-6: 数据解析
- [ ] 实现HTML解析器
- [ ] 提取人物基本信息
- [ ] 提取作品信息
- [ ] 提取关系信息

### Day 7: 数据验证
- [ ] 实现数据验证规则
- [ ] 爬取10个测试数据
- [ ] 验证数据质量
- [ ] 编写测试报告

## 数据模型

### 人物实体（Person）
```python
{
  "id": "person_001",
  "name": "周杰伦",
  "name_en": "Jay Chou",
  "gender": "male",
  "birth_date": "1979-01-18",
  "birth_place": "台湾省新北市",
  "nationality": "中国",
  "summary": "华语流行乐男歌手、音乐人...",
  "categories": ["singer", "actor", "director"]
}
```

### 作品实体（Work）
```python
{
  "id": "work_001",
  "title": "七里香",
  "type": "album",
  "release_date": "2004-08-03",
  "genre": "流行",
  "rating": 9.0
}
```

### 关系（Relation）
```python
{
  "source": "person_001",
  "target": "person_002",
  "type": "MARRIED_TO",
  "properties": {
    "start_date": "2015-01-17"
  }
}
```

## 爬虫设计

### 基类
```python
# crawler/base.py
class BaseCrawler:
    def __init__(self):
        self.session = requests.Session()
        self.delay = 1.0  # 请求间隔（秒）
    
    def fetch(self, url: str) -> str:
        """获取页面内容"""
        time.sleep(self.delay)
        response = self.session.get(url)
        response.raise_for_status()
        return response.text
    
    def parse(self, html: str) -> dict:
        """解析页面"""
        raise NotImplementedError
```

### 维基百科爬虫
```python
# crawler/wikipedia.py
class WikipediaCrawler(BaseCrawler):
    BASE_URL = "https://zh.wikipedia.org/wiki/"
    
    def crawl_person(self, name: str) -> dict:
        """爬取人物页面"""
        url = self.BASE_URL + name
        html = self.fetch(url)
        return self.parse(html)
    
    def parse(self, html: str) -> dict:
        """解析人物页面"""
        soup = BeautifulSoup(html, 'lxml')
        
        # 提取基本信息
        data = {
            "name": self._extract_name(soup),
            "birth_date": self._extract_birth_date(soup),
            "summary": self._extract_summary(soup),
            # ...
        }
        
        return data
```

## 数据清洗

### 清洗规则
```python
# crawler/cleaner.py
class DataCleaner:
    def clean_person(self, data: dict) -> dict:
        """清洗人物数据"""
        # 去除空白字符
        data['name'] = data['name'].strip()
        
        # 标准化日期
        if data.get('birth_date'):
            data['birth_date'] = self._standardize_date(data['birth_date'])
        
        # 过滤无效数据
        if not data.get('name'):
            raise ValueError("人物姓名不能为空")
        
        return data
    
    def _standardize_date(self, date_str: str) -> str:
        """标准化日期格式"""
        # 处理各种日期格式
        # 返回 ISO 8601 格式
        pass
```

## 实体识别

### 基于规则
```python
# crawler/ner.py
class RuleBasedNER:
    def extract_persons(self, text: str) -> list:
        """从文本中提取人名"""
        # 使用正则表达式或词典匹配
        pass
    
    def extract_works(self, text: str) -> list:
        """从文本中提取作品名"""
        pass
```

### 基于LLM（备用）
```python
class LLMBasedNER:
    def __init__(self):
        self.llm = OpenAI()
    
    def extract(self, text: str) -> dict:
        """使用LLM提取实体"""
        prompt = f"""
        从以下文本中提取实体：
        {text}
        
        返回JSON格式：
        {{
            "persons": ["人名1", "人名2"],
            "works": ["作品1", "作品2"],
            "companies": ["公司1"]
        }}
        """
        return self.llm.predict(prompt)
```

## 关系抽取

```python
# crawler/relation.py
class RelationExtractor:
    def extract_relations(self, text: str, person_name: str) -> list:
        """从文本中提取关系"""
        relations = []
        
        # 婚姻关系
        if '妻子' in text or '丈夫' in text:
            spouse = self._extract_spouse(text)
            relations.append({
                "source": person_name,
                "target": spouse,
                "type": "MARRIED_TO"
            })
        
        # 合作关系
        if '合作' in text:
            collaborators = self._extract_collaborators(text)
            for collab in collaborators:
                relations.append({
                    "source": person_name,
                    "target": collab,
                    "type": "COLLABORATED_WITH"
                })
        
        return relations
```

## 数据验证

### 验证规则
```python
# crawler/validator.py
class DataValidator:
    def validate_person(self, data: dict) -> bool:
        """验证人物数据"""
        # 必填字段
        required = ['id', 'name', 'summary']
        for field in required:
            if not data.get(field):
                raise ValueError(f"缺少必填字段: {field}")
        
        # 字段类型
        if not isinstance(data['name'], str):
            raise TypeError("name必须是字符串")
        
        # 字段长度
        if len(data['name']) < 2:
            raise ValueError("name长度必须大于2")
        
        return True
```

## Neo4j导入

```python
# scripts/import_neo4j.py
from neo4j import GraphDatabase

class Neo4jImporter:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
    
    def import_person(self, person: dict):
        """导入人物"""
        with self.driver.session() as session:
            session.run("""
                CREATE (p:Person {
                    id: $id,
                    name: $name,
                    name_en: $name_en,
                    birth_date: $birth_date,
                    summary: $summary
                })
            """, person)
    
    def import_relation(self, relation: dict):
        """导入关系"""
        with self.driver.session() as session:
            session.run("""
                MATCH (a:Person {id: $source})
                MATCH (b:Person {id: $target})
                CREATE (a)-[r:MARRIED_TO]->(b)
                SET r.start_date = $start_date
            """, relation)
```

## 数据质量监控

### 监控指标
```python
class DataQualityMonitor:
    def check_completeness(self, data: list) -> float:
        """检查数据完整率"""
        total = len(data)
        complete = sum(1 for d in data if self._is_complete(d))
        return complete / total
    
    def check_accuracy(self, data: list) -> float:
        """检查数据准确率"""
        # 抽样人工检查
        pass
    
    def generate_report(self) -> dict:
        """生成质量报告"""
        return {
            "total_records": 1000,
            "complete_rate": 0.95,
            "accuracy_rate": 0.90,
            "issues": [
                {"type": "missing_birth_date", "count": 50},
                {"type": "wrong_relation", "count": 10}
            ]
        }
```

## 与其他角色的协作

| 协作对象 | 协作内容 | 频率 |
|---------|---------|------|
| 后端工程师 | 数据模型、查询优化 | 每日 |
| PM | 数据质量报告、进度同步 | 每日 |
| 前端工程师 | 数据展示格式 | 按需 |

## 常见问题

### Q: 维基百科反爬怎么办？
A: 控制请求频率（≤1req/s），使用User-Agent池，必要时使用代理。

### Q: 数据不一致怎么办？
A: 建立主数据源（维基百科），其他数据源作为补充，冲突时人工审核。

### Q: 实体消歧怎么做？
A: 使用上下文信息、属性匹配，必要时人工标注。

### Q: 如何增量更新？
A: 记录上次更新时间，只爬取变更页面，使用版本控制。
