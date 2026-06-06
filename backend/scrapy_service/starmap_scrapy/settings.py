"""
Scrapy settings for starmap_scrapy project.

For simplicity, this file contains only the most important settings by default.
All the other settings are documented here:
    https://docs.scrapy.org/en/latest/topics/settings.html
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent

# Project name
BOT_NAME = "starmap_scrapy"

# Spider modules
SPIDER_MODULES = ["starmap_scrapy.spiders"]
NEWSPIDER_MODULE = "starmap_scrapy.spiders"

# Crawl responsibly by identifying yourself (and your website) on the user-agent
USER_AGENT = "StarMapBot/1.0 (+https://github.com/Si1ive/starmap)"

# Obey robots.txt rules
ROBOTSTXT_OBEY = True

# Configure maximum concurrent requests performed by Scrapy (default: 16)
CONCURRENT_REQUESTS = 4

# Configure a delay for requests for the same website (default: 0)
DOWNLOAD_DELAY = 1
# The download delay setting will honor only one of:
CONCURRENT_REQUESTS_PER_DOMAIN = 2

# Disable cookies (enabled by default)
COOKIES_ENABLED = False

# Disable Telnet Console (enabled by default)
TELNETCONSOLE_ENABLED = False

# Override the default request headers:
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Enable or disable spider middlewares
SPIDER_MIDDLEWARES = {
    "starmap_scrapy.middlewares.StarMapSpiderMiddleware": 543,
}

# Enable or disable downloader middlewares
DOWNLOADER_MIDDLEWARES = {
    "starmap_scrapy.middlewares.StarMapDownloaderMiddleware": 543,
    "starmap_scrapy.middlewares.RotateUserAgentMiddleware": 400,
}

# Enable or disable extensions
EXTENSIONS = {
    "starmap_scrapy.extensions.progress_reporter.ProgressReporterExtension": 200,
}

# Configure item pipelines
ITEM_PIPELINES = {
    "starmap_scrapy.pipelines.validation.ValidationPipeline": 100,
    "starmap_scrapy.pipelines.storage.DatabasePipeline": 200,
    "starmap_scrapy.pipelines.storage.Neo4jPipeline": 300,
}

# Enable and configure the AutoThrottle extension (disabled by default)
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0
AUTOTHROTTLE_DEBUG = False

# Enable showing throttling stats for every response received:
# AUTOTHROTTLE_DEBUG = True

# Configure HTTP caching (disabled by default)
# HTTPCACHE_ENABLED = True
# HTTPCACHE_EXPIRATION_SECS = 0
# HTTPCACHE_DIR = "httpcache"
# HTTPCACHE_IGNORE_HTTP_CODES = []
# HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

# Set settings whose default value is deprecated to a future-proof value
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# Redis settings
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_TASK_QUEUE = "starmap:crawl:tasks"
REDIS_PROGRESS_CHANNEL = "starmap:crawl:progress"
REDIS_LOG_CHANNEL = "starmap:crawl:logs"

# MySQL settings
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "starmap")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "starmap123")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "starmap")

# Neo4j settings
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "starmap123")

# StarMap API settings
STARMAP_API_URL = os.getenv("STARMAP_API_URL", "http://localhost:8000")

# Retry settings
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# Timeout settings
DOWNLOAD_TIMEOUT = 30
