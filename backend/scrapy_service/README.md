# StarMap Scrapy Service

独立爬虫服务，基于 Scrapy 框架，负责实际的网页爬取和数据提取。

## 架构

```
┌─────────────┐     Redis队列      ┌─────────────────┐
│  FastAPI    │ ────────────────► │  Scrapy Service │
│  主服务      │                   │  (本服务)        │
│             │ ◄──────────────── │                 │
└─────────────┘   进度/日志频道    │  - 反爬处理     │
                                   │  - 数据解析     │
                                   │  - 结果写入     │
                                   └─────────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
cd scrapy_service
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，配置数据库连接
```

### 3. 运行服务

#### 方式一：任务消费模式（推荐）

持续监听 Redis 队列，等待 FastAPI 发布任务：

```bash
python main.py --mode consumer
```

#### 方式二：单次任务模式

直接运行单个爬取任务：

```bash
python main.py --mode single \
  --spider person \
  --source baike \
  --keywords "周杰伦"
```

### 4. 使用 Podman 部署

```bash
# 构建并启动
./podman-build.sh start

# 查看状态
./podman-build.sh status

# 查看日志
./podman-build.sh logs

# 停止服务
./podman-build.sh stop
```

## 项目结构

```
scrapy_service/
├── main.py                      # 服务入口
├── requirements.txt             # Python依赖
├── Dockerfile                   # 容器构建
├── podman-build.sh             # Podman部署脚本
├── scrapy.cfg                   # Scrapy配置
└── starmap_scrapy/             # Scrapy项目
    ├── settings.py             # Scrapy设置
    ├── items.py                # 数据模型
    ├── middlewares.py          # 中间件
    ├── extensions/             # 扩展
    │   └── progress_reporter.py # 进度上报
    ├── pipelines/              # 数据管道
    │   ├── validation.py      # 数据验证
    │   └── storage.py         # 数据存储
    └── spiders/                # 爬虫
        ├── person_spider.py   # 人物爬虫
        └── work_spider.py     # 作品爬虫
```

## 支持的爬虫

| 爬虫名称 | 说明 | 数据源 |
|---------|------|--------|
| person | 人物信息爬取 | 百度百科、豆瓣、维基百科 |
| work | 作品信息爬取 | 豆瓣、百度百科 |

## 数据模型

### PersonItem

```python
{
    "id": "person_xxx",
    "name": "姓名",
    "name_en": "英文名",
    "avatar": "头像URL",
    "gender": "male/female/unknown",
    "birth_date": "出生日期",
    "birth_place": "出生地",
    "nationality": "国籍",
    "height": 1.75,
    "summary": "简介",
    "biography": "详细传记",
    "categories": ["演员", "歌手"],
    "source": "baike",
    "source_url": "...",
    "crawl_task_id": "task_xxx"
}
```

### WorkItem

```python
{
    "id": "work_xxx",
    "title": "标题",
    "type": "movie/tv/album/single/book",
    "release_date": "发行日期",
    "genre": "类型",
    "rating": 8.5,
    "director": ["导演名"],
    "actors": ["演员名"],
    "source": "douban",
    "source_url": "...",
    "crawl_task_id": "task_xxx"
}
```

## 配置说明

### Scrapy Settings

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| CONCURRENT_REQUESTS | 并发请求数 | 4 |
| DOWNLOAD_DELAY | 请求间隔(秒) | 1 |
| AUTOTHROTTLE_ENABLED | 自动限速 | True |
| RETRY_TIMES | 重试次数 | 3 |

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| REDIS_URL | Redis连接URL | redis://localhost:6379/0 |
| MYSQL_HOST | MySQL主机 | localhost |
| MYSQL_PORT | MySQL端口 | 3306 |
| MYSQL_USER | MySQL用户 | starmap |
| MYSQL_PASSWORD | MySQL密码 | starmap123 |
| NEO4J_URI | Neo4j URI | bolt://localhost:7687 |
| LOG_LEVEL | 日志级别 | INFO |

## 开发指南

### 添加新爬虫

1. 在 `starmap_scrapy/spiders/` 创建新的 Spider 类
2. 继承 `scrapy.Spider`
3. 实现 `parse` 方法
4. 返回 `PersonItem` 或 `WorkItem`

示例：

```python
import scrapy
from starmap_scrapy.items import PersonItem

class MySpider(scrapy.Spider):
    name = "my_spider"
    
    def start_requests(self):
        yield scrapy.Request(url="https://example.com")
    
    def parse(self, response):
        yield PersonItem(
            name="示例",
            source="example",
            source_url=response.url,
        )
```

### 添加新 Pipeline

1. 在 `starmap_scrapy/pipelines/` 创建 Pipeline 类
2. 实现 `process_item` 方法
3. 在 `settings.py` 中注册

## 监控

### 查看爬虫统计

```bash
# 进入 Scrapy shell
scrapy shell "https://baike.baidu.com/item/周杰伦"

# 测试爬虫
scrapy crawl person -a keywords=周杰伦 -L INFO
```

### 日志位置

- 容器内: `/app/logs/`
- 宿主机: 挂载的 volumes 目录

### 队列消费机制

`python main.py --mode consumer` 会常驻监听 Redis `starmap:crawl:tasks` 队列。每个任务以独立子进程执行 `single` 模式，避免 Scrapy/Twisted reactor 在同一进程内重复启动。

## 故障排查

### 常见问题

1. **Redis 连接失败**
   - 检查 Redis 服务是否运行
   - 确认 `REDIS_URL` 配置正确

2. **MySQL 连接失败**
   - 检查 MySQL 服务是否运行
   - 确认数据库用户权限

3. **爬虫被反爬**
   - 增加 `DOWNLOAD_DELAY`
   - 启用代理池
   - 更换 User-Agent

### 调试模式

```bash
# 启用 DEBUG 日志
LOG_LEVEL=DEBUG python main.py --mode single --keywords "周杰伦"
```

## License

MIT License - 同 StarMap 项目
