"""
Scrapy settings for 408考研学习平台爬虫服务.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

BOT_NAME = "crawler_service"

SPIDER_MODULES = ["starmap_scrapy.spiders"]
NEWSPIDER_MODULE = "starmap_scrapy.spiders"

USER_AGENT = "408StudyBot/1.0"
ROTATE_USER_AGENT_ENABLED = True

ROBOTSTXT_OBEY = False

CONCURRENT_REQUESTS = 4
DOWNLOAD_DELAY = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 2
GLOBAL_PROXY_URL = ""

COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False

DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

SPIDER_MIDDLEWARES = {
    "starmap_scrapy.middlewares.StarMapSpiderMiddleware": 543,
}

DOWNLOADER_MIDDLEWARES = {
    "starmap_scrapy.middlewares.StarMapDownloaderMiddleware": 543,
    "starmap_scrapy.middlewares.RotateUserAgentMiddleware": 400,
}

EXTENSIONS = {
    "starmap_scrapy.extensions.progress_reporter.ProgressReporterExtension": 200,
}

ITEM_PIPELINES = {
    "starmap_scrapy.pipelines.validation.ValidationPipeline": 100,
    "starmap_scrapy.pipelines.storage.DatabasePipeline": 200,
}

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0
AUTOTHROTTLE_DEBUG = False

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# Redis settings
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_TASK_QUEUE = "crawler:tasks"
REDIS_PROGRESS_CHANNEL = "crawler:progress"
REDIS_LOG_CHANNEL = "crawler:logs"

# MySQL settings
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "starmap")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "starmap123")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "starmap")

# GitHub settings
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Download storage
DOWNLOAD_STORE = os.getenv("DOWNLOAD_STORE", str(BASE_DIR.parent.parent / "downloads"))

# Retry settings
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# Timeout settings
DOWNLOAD_TIMEOUT = 60
