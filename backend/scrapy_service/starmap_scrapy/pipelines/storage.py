"""
Storage Pipelines for Scrapy Items.

Writes validated items to MySQL database.
"""

import json
import logging
import re
import uuid
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

import pymysql
from pymysql.cursors import DictCursor

from starmap_scrapy.items import FileDownloadItem, CrawlLogItem, KnowledgePointItem, QuestionItem

logger = logging.getLogger(__name__)


class DatabasePipeline:
    """Pipeline for storing items in MySQL database."""

    def __init__(self, mysql_config):
        self.mysql_config = mysql_config
        self.connection = None
        self.cursor = None
        self.stats = {
            "files_inserted": 0,
            "files_succeeded": 0,
            "files_failed": 0,
            "logs_inserted": 0,
            "knowledge_points_inserted": 0,
            "questions_inserted": 0,
            "errors": 0,
        }

    @classmethod
    def from_crawler(cls, crawler):
        mysql_config = {
            "host": crawler.settings.get("MYSQL_HOST", "localhost"),
            "port": crawler.settings.get("MYSQL_PORT", 3306),
            "user": crawler.settings.get("MYSQL_USER", "starmap"),
            "password": crawler.settings.get("MYSQL_PASSWORD", "starmap123"),
            "database": crawler.settings.get("MYSQL_DATABASE", "starmap"),
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
        }
        return cls(mysql_config)

    def open_spider(self, spider):
        try:
            self.connection = pymysql.connect(**self.mysql_config)
            self.cursor = self.connection.cursor()
            logger.info("Database connection opened")
        except Exception as e:
            logger.error(f"Failed to open database connection: {e}")
            raise

    def close_spider(self, spider):
        # Expose pipeline stats on spider for progress reporter
        spider.pipeline_stats = self.stats
        if self.connection:
            try:
                self._upsert_source_stats(spider)
                self.connection.commit()
            except Exception as e:
                logger.error(f"Error persisting crawl source stats: {e}")
                self.connection.rollback()
            finally:
                self.connection.close()
                logger.info(f"Database connection closed. Stats: {self.stats}")

    def process_item(self, item, spider):
        try:
            if isinstance(item, FileDownloadItem):
                self._store_downloaded_file(item)
            elif isinstance(item, CrawlLogItem):
                self._store_log(item)
            elif isinstance(item, KnowledgePointItem):
                self._store_knowledge_point(item)
            elif isinstance(item, QuestionItem):
                self._store_question(item)
            else:
                logger.warning(f"Unknown item type: {type(item).__name__}")
            return item
        except Exception as e:
            logger.error(f"Failed to store item: {e}")
            self.stats["errors"] += 1
            return item

    def _store_downloaded_file(self, item: FileDownloadItem):
        file_id = self._generate_id("file")

        # Extract error detail from metadata
        error_detail = None
        metadata = item.get("metadata")
        if metadata and isinstance(metadata, dict):
            error_detail = metadata.get("error")

        sql = """
            INSERT INTO downloaded_files (
                id, task_id, repo_name, repo_url, file_path,
                file_name, file_type, file_size, download_url,
                local_path, status, error_detail, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                local_path = VALUES(local_path),
                file_size = VALUES(file_size),
                status = VALUES(status),
                error_detail = VALUES(error_detail),
                updated_at = VALUES(updated_at)
        """

        params = (
            file_id,
            item.get("task_id"),
            item.get("repo_name"),
            item.get("repo_url"),
            item.get("file_path"),
            item.get("file_name"),
            item.get("file_type"),
            item.get("file_size"),
            item.get("download_url"),
            item.get("local_path"),
            item.get("status", "downloaded"),
            error_detail,
            self._normalize_datetime(item.get("created_at")),
            self._normalize_datetime(item.get("updated_at")),
        )

        self.cursor.execute(sql, params)
        self.connection.commit()
        self.stats["files_inserted"] += 1
        if item.get("status") == "failed":
            self.stats["files_failed"] += 1
        else:
            self.stats["files_succeeded"] += 1
        logger.debug(f"Stored downloaded file: {item.get('file_name')} ({file_id}) status={item.get('status')}")

    def _store_log(self, item: CrawlLogItem):
        sql = """
            INSERT INTO crawl_logs (
                task_id, source_id, level, stage,
                resource_url, resource_name, resource_type,
                action, status, duration_ms, message,
                error_type, error_detail, retry_count, details, created_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
        """

        params = (
            item.get("task_id"),
            item.get("source_id"),
            item.get("level", "INFO"),
            item.get("stage"),
            item.get("resource_url"),
            item.get("resource_name"),
            item.get("resource_type"),
            item.get("action"),
            item.get("status", "pending"),
            item.get("duration_ms"),
            item.get("message"),
            item.get("error_type"),
            item.get("error_detail"),
            item.get("retry_count", 0),
            json.dumps(item.get("details", {}), ensure_ascii=False, default=str),
            self._normalize_datetime(item.get("created_at")),
        )

        self.cursor.execute(sql, params)
        self.connection.commit()
        self.stats["logs_inserted"] += 1

    def _store_knowledge_point(self, item: KnowledgePointItem):
        point_id = item.get("id") or self._generate_id("kp")

        sql = """
            INSERT INTO knowledge_points (
                id, chapter_id, subject_id, title, content,
                difficulty, exam_frequency, tags, key_points,
                related_point_ids, source, source_page,
                crawl_task_id, status, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                chapter_id = VALUES(chapter_id),
                subject_id = VALUES(subject_id),
                title = VALUES(title),
                content = VALUES(content),
                difficulty = VALUES(difficulty),
                exam_frequency = VALUES(exam_frequency),
                tags = VALUES(tags),
                key_points = VALUES(key_points),
                related_point_ids = VALUES(related_point_ids),
                source = VALUES(source),
                source_page = VALUES(source_page),
                crawl_task_id = VALUES(crawl_task_id),
                status = VALUES(status),
                updated_at = VALUES(updated_at)
        """

        params = (
            point_id,
            item.get("chapter_id"),
            item.get("subject_id"),
            item.get("title"),
            item.get("content"),
            item.get("difficulty", "medium"),
            item.get("exam_frequency", "medium"),
            json.dumps(item.get("tags", []), ensure_ascii=False),
            json.dumps(item.get("key_points", []), ensure_ascii=False),
            json.dumps(item.get("related_point_ids", []), ensure_ascii=False),
            item.get("source"),
            item.get("source_page"),
            item.get("crawl_task_id"),
            item.get("status", "active"),
            self._normalize_datetime(item.get("created_at")),
            self._normalize_datetime(item.get("updated_at")),
        )

        self.cursor.execute(sql, params)
        self.connection.commit()
        self.stats["knowledge_points_inserted"] += 1

    def _store_question(self, item: QuestionItem):
        question_id = item.get("id") or self._generate_id("q")

        sql = """
            INSERT INTO questions (
                id, subject_id, chapter_id, type, content,
                options, answer, explanation, difficulty,
                source, exam_year, knowledge_point_ids,
                tags, status, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                subject_id = VALUES(subject_id),
                chapter_id = VALUES(chapter_id),
                type = VALUES(type),
                content = VALUES(content),
                options = VALUES(options),
                answer = VALUES(answer),
                explanation = VALUES(explanation),
                difficulty = VALUES(difficulty),
                source = VALUES(source),
                exam_year = VALUES(exam_year),
                knowledge_point_ids = VALUES(knowledge_point_ids),
                tags = VALUES(tags),
                status = VALUES(status),
                updated_at = VALUES(updated_at)
        """

        params = (
            question_id,
            item.get("subject_id"),
            item.get("chapter_id"),
            item.get("type"),
            item.get("content"),
            json.dumps(item.get("options", []), ensure_ascii=False),
            item.get("answer"),
            item.get("explanation"),
            item.get("difficulty", "medium"),
            item.get("source"),
            item.get("exam_year", 0),
            json.dumps(item.get("knowledge_point_ids", []), ensure_ascii=False),
            json.dumps(item.get("tags", []), ensure_ascii=False),
            item.get("status", "active"),
            self._normalize_datetime(item.get("created_at")),
            self._normalize_datetime(item.get("updated_at")),
        )

        self.cursor.execute(sql, params)
        self.connection.commit()
        self.stats["questions_inserted"] += 1

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def _normalize_date(self, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        match = re.search(r"(\d{4})(?:[-年/.](\d{1,2}))?(?:[-月/.](\d{1,2}))?", text)
        if not match:
            return None
        year = int(match.group(1))
        month = int(match.group(2) or 1)
        day = int(match.group(3) or 1)
        try:
            return datetime(year, month, day).date()
        except ValueError:
            return None

    def _normalize_datetime(self, value):
        if not value:
            return datetime.utcnow()
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return datetime.utcnow()

    def _normalize_decimal(self, value, default=None):
        if value is None:
            return default
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return default

    def _upsert_source_stats(self, spider):
        source_id = self._resolve_source_id(spider)
        if not source_id:
            logger.warning("Skip crawl_source_stats upsert: source_id not found")
            return

        crawler_stats = getattr(getattr(spider, "crawler", None), "stats", None)
        get_value = crawler_stats.get_value if crawler_stats else lambda key, default=0: default

        total_requests = int(get_value("downloader/request_count", 0) or 0)
        response_count = int(get_value("downloader/response_count", 0) or 0)
        status_failures = sum(
            int(get_value(f"downloader/response_status_count/{status}", 0) or 0)
            for status in range(400, 600)
        )
        exception_count = int(get_value("downloader/exception_count", 0) or 0)
        failed_requests = max(status_failures + exception_count, self.stats["errors"])
        success_requests = max(response_count - failed_requests, 0)
        valid_records = self.stats["files_inserted"]
        duration = int(get_value("elapsed_time_seconds", 0) or 0)
        avg_response_time = round((duration * 1000) / response_count, 2) if response_count else None

        sql = """
            INSERT INTO crawl_source_stats (
                source_id, stat_date, total_requests, success_requests, failed_requests,
                timeout_requests, rate_limited_requests, files_extracted,
                valid_records, duplicate_records, total_duration,
                avg_response_time, created_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            ON DUPLICATE KEY UPDATE
                total_requests = total_requests + VALUES(total_requests),
                success_requests = success_requests + VALUES(success_requests),
                failed_requests = failed_requests + VALUES(failed_requests),
                timeout_requests = timeout_requests + VALUES(timeout_requests),
                rate_limited_requests = rate_limited_requests + VALUES(rate_limited_requests),
                files_extracted = files_extracted + VALUES(files_extracted),
                valid_records = valid_records + VALUES(valid_records),
                duplicate_records = duplicate_records + VALUES(duplicate_records),
                total_duration = total_duration + VALUES(total_duration)
        """
        params = (
            source_id,
            datetime.utcnow().date(),
            total_requests,
            success_requests,
            failed_requests,
            int(get_value("downloader/exception_type_count/twisted.internet.error.TimeoutError", 0) or 0),
            int(get_value("downloader/response_status_count/429", 0) or 0),
            self.stats["files_inserted"],
            valid_records,
            0,
            duration,
            avg_response_time,
            datetime.utcnow(),
        )
        self.cursor.execute(sql, params)
        self._update_source_totals(source_id, total_requests, success_requests, failed_requests, avg_response_time)
        logger.info("Upserted crawl_source_stats for source_id=%s", source_id)

    def _resolve_source_id(self, spider):
        source_id = getattr(spider, "source_id", None)
        if source_id:
            return source_id

        source_code = getattr(spider, "source", None)
        if not source_code:
            return None

        self.cursor.execute(
            "SELECT id FROM crawl_sources WHERE code = %s LIMIT 1",
            (source_code,),
        )
        row = self.cursor.fetchone()
        if row:
            return row["id"]
        return self._create_default_source(source_code)

    def _create_default_source(self, source_code):
        defaults = {
            "github": ("GitHub", "github", "code_hosting", "https://github.com"),
        }
        name, code, source_type, base_url = defaults.get(
            source_code,
            (source_code, source_code, "other", None),
        )
        source_id = f"src_{uuid.uuid4().hex[:8]}"
        sql = """
            INSERT INTO crawl_sources (
                id, name, code, type, base_url, config, status,
                health_status, request_interval, daily_limit, concurrent_limit,
                total_requests, total_success, total_failed, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE updated_at = VALUES(updated_at)
        """
        self.cursor.execute(
            sql,
            (
                source_id, name, code, source_type, base_url,
                json.dumps({}, ensure_ascii=False),
                "active", "healthy", 1.0, 5000, 5,
                0, 0, 0, datetime.utcnow(), datetime.utcnow(),
            ),
        )
        self.cursor.execute("SELECT id FROM crawl_sources WHERE code = %s LIMIT 1", (code,))
        row = self.cursor.fetchone()
        return row["id"] if row else source_id

    def _update_source_totals(self, source_id, total_requests, success_requests, failed_requests, avg_response_time):
        sql = """
            UPDATE crawl_sources
            SET avg_response_time = CASE
                    WHEN %s IS NULL THEN avg_response_time
                    WHEN (total_requests + %s) > 0 THEN
                        ROUND(((COALESCE(avg_response_time, 0) * total_requests) + (%s * %s)) / (total_requests + %s), 2)
                    ELSE %s
                END,
                total_requests = total_requests + %s,
                total_success = total_success + %s,
                total_failed = total_failed + %s,
                updated_at = %s
            WHERE id = %s
        """
        self.cursor.execute(
            sql,
            (
                avg_response_time, total_requests,
                avg_response_time or 0, total_requests, total_requests,
                avg_response_time,
                total_requests, success_requests, failed_requests,
                datetime.utcnow(), source_id,
            ),
        )
