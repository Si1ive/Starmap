"""
Storage Pipelines for Scrapy Items.

Writes validated items to MySQL and Neo4j databases.
"""

import json
import logging
import re
import uuid
from datetime import datetime
from datetime import date
from decimal import Decimal, InvalidOperation

import pymysql
from pymysql.cursors import DictCursor

from starmap_scrapy.items import PersonItem, WorkItem, RelationItem, CrawlLogItem

logger = logging.getLogger(__name__)

VALID_WORK_TYPES = {"album", "movie", "tv", "drama", "book", "single", "ep"}


class DatabasePipeline:
    """
    Pipeline for storing items in MySQL database.
    
    Uses pymysql for synchronous database operations.
    Reuses the existing StarMap database schema.
    """

    def __init__(self, mysql_config):
        self.mysql_config = mysql_config
        self.connection = None
        self.cursor = None
        self.stats = {
            "persons_inserted": 0,
            "works_inserted": 0,
            "relations_inserted": 0,
            "logs_inserted": 0,
            "errors": 0,
        }

    @classmethod
    def from_crawler(cls, crawler):
        """Create pipeline instance from crawler settings."""
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
        """Open database connection when spider starts."""
        try:
            self.connection = pymysql.connect(**self.mysql_config)
            self.cursor = self.connection.cursor()
            logger.info("Database connection opened")
        except Exception as e:
            logger.error(f"Failed to open database connection: {e}")
            raise

    def close_spider(self, spider):
        """Close database connection when spider finishes."""
        if self.connection:
            try:
                self._upsert_source_stats(spider)
                self.connection.commit()
            except Exception as e:
                logger.error(f"Error persisting crawl source stats: {e}")
                self.connection.rollback()
            finally:
                self.connection.close()
                logger.info(
                    f"Database connection closed. Stats: {self.stats}"
                )

    def process_item(self, item, spider):
        """Process item and store in database."""
        try:
            if isinstance(item, PersonItem):
                self._store_person(item)
            elif isinstance(item, WorkItem):
                self._store_work(item)
            elif isinstance(item, RelationItem):
                self._store_relation(item)
            elif isinstance(item, CrawlLogItem):
                self._store_log(item)
            else:
                logger.warning(f"Unknown item type: {type(item).__name__}")
            
            return item
            
        except Exception as e:
            logger.error(f"Failed to store item: {e}")
            self.stats["errors"] += 1
            # Don't drop the item, just log the error
            return item

    def _store_person(self, item: PersonItem):
        """Store person item in database."""
        # Generate ID if not provided
        person_id = item.get("id") or self._generate_id("person")
        
        sql = """
            INSERT INTO persons (
                id, name, name_en, avatar, gender, birth_date, birth_place,
                nationality, height, summary, biography, categories,
                status, data_quality_score, crawl_source, crawl_url,
                crawl_task_id, raw_data, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                name_en = VALUES(name_en),
                avatar = VALUES(avatar),
                gender = VALUES(gender),
                birth_date = VALUES(birth_date),
                birth_place = VALUES(birth_place),
                nationality = VALUES(nationality),
                height = VALUES(height),
                summary = VALUES(summary),
                biography = VALUES(biography),
                categories = VALUES(categories),
                status = VALUES(status),
                data_quality_score = VALUES(data_quality_score),
                crawl_source = VALUES(crawl_source),
                crawl_url = VALUES(crawl_url),
                crawl_task_id = VALUES(crawl_task_id),
                raw_data = VALUES(raw_data),
                updated_at = VALUES(updated_at)
        """
        
        params = (
            person_id,
            item.get("name"),
            item.get("name_en"),
            item.get("avatar"),
            item.get("gender"),
            self._normalize_date(item.get("birth_date")),
            item.get("birth_place"),
            item.get("nationality"),
            item.get("height"),
            item.get("summary"),
            item.get("biography"),
            json.dumps(item.get("categories", []), ensure_ascii=False),
            item.get("status", "pending"),
            self._normalize_decimal(item.get("data_quality_score"), default=0.0),
            item.get("source"),
            item.get("source_url"),
            item.get("crawl_task_id"),
            json.dumps(item.get("raw_data", {}), ensure_ascii=False, default=str),
            self._normalize_datetime(item.get("created_at")),
            self._normalize_datetime(item.get("updated_at")),
        )
        
        self.cursor.execute(sql, params)
        self.connection.commit()
        self.stats["persons_inserted"] += 1
        
        # Update item with generated ID
        item["id"] = person_id
        logger.debug(f"Stored person: {item.get('name')} ({person_id})")

    def _store_work(self, item: WorkItem):
        """Store work item in database."""
        work_id = item.get("id") or self._generate_id("work")
        
        sql = """
            INSERT INTO works (
                id, title, title_en, type, release_date, genre,
                rating, poster, summary, status, crawl_source, crawl_url,
                crawl_task_id, raw_data, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                title_en = VALUES(title_en),
                type = VALUES(type),
                release_date = VALUES(release_date),
                genre = VALUES(genre),
                rating = VALUES(rating),
                poster = VALUES(poster),
                summary = VALUES(summary),
                status = VALUES(status),
                crawl_source = VALUES(crawl_source),
                crawl_url = VALUES(crawl_url),
                crawl_task_id = VALUES(crawl_task_id),
                raw_data = VALUES(raw_data),
                updated_at = VALUES(updated_at)
        """
        raw_data = item.get("raw_data", {})
        if not isinstance(raw_data, dict):
            raw_data = {"value": raw_data}
        raw_data = {
            **raw_data,
            "director": item.get("director", []),
            "actors": item.get("actors", []),
            "episodes": item.get("episodes"),
            "platform": item.get("platform"),
            "box_office": item.get("box_office"),
            "artist": item.get("artist", []),
            "record_company": item.get("record_company"),
            "track_list": item.get("track_list", []),
            "author": item.get("author", []),
            "publisher": item.get("publisher"),
            "isbn": item.get("isbn"),
            "related_persons": item.get("related_persons", []),
        }
        
        params = (
            work_id,
            item.get("title"),
            item.get("title_en"),
            self._normalize_work_type(item.get("type")),
            self._normalize_date(item.get("release_date")),
            item.get("genre"),
            self._normalize_decimal(item.get("rating")),
            item.get("poster"),
            item.get("summary"),
            item.get("status", "pending"),
            item.get("source"),
            item.get("source_url"),
            item.get("crawl_task_id"),
            json.dumps(raw_data, ensure_ascii=False, default=str),
            self._normalize_datetime(item.get("created_at")),
            self._normalize_datetime(item.get("updated_at")),
        )
        
        self.cursor.execute(sql, params)
        self.connection.commit()
        self.stats["works_inserted"] += 1
        
        item["id"] = work_id
        logger.debug(f"Stored work: {item.get('title')} ({work_id})")

    def _store_relation(self, item: RelationItem):
        """Store relation item in database."""
        if not item.get("source_id") or not item.get("target_id"):
            logger.info("Skipping relation without source_id/target_id")
            return

        relation_type = self._normalize_relation_type(item.get("relation_type"))
        
        sql = """
            INSERT INTO person_relations (
                source_id, target_id, relation_type, properties,
                confidence, source, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                relation_type = VALUES(relation_type),
                properties = VALUES(properties),
                confidence = VALUES(confidence),
                source = VALUES(source),
                updated_at = VALUES(updated_at)
        """
        properties = {
            "role": item.get("role"),
            "crawl_task_id": item.get("crawl_task_id"),
            "raw_relation_type": item.get("relation_type"),
        }
        now = datetime.utcnow()
        
        params = (
            item.get("source_id"),
            item.get("target_id"),
            relation_type,
            json.dumps(properties, ensure_ascii=False, default=str),
            self._normalize_decimal(item.get("confidence"), default=1.0),
            item.get("source"),
            self._normalize_datetime(item.get("created_at")) or now,
            self._normalize_datetime(item.get("updated_at")) or now,
        )
        
        self.cursor.execute(sql, params)
        self.connection.commit()
        self.stats["relations_inserted"] += 1
        
        logger.debug(
            "Stored relation: %s -> %s (%s)",
            item.get("source_id"),
            item.get("target_id"),
            relation_type,
        )

    def _store_log(self, item: CrawlLogItem):
        """Store crawl log item in database."""
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

    def _generate_id(self, prefix: str) -> str:
        """Generate a unique ID."""
        import uuid
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def _normalize_date(self, value):
        """Convert noisy scraped date strings to MySQL DATE-compatible values."""
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
        """Convert item timestamp values to MySQL DATETIME-compatible values."""
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
        """Convert scraped numeric values to a Decimal-compatible value."""
        if value is None:
            return default
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return default

    def _normalize_work_type(self, work_type: str) -> str:
        """Map spider work types to the current MySQL enum."""
        mapping = {
            "music": "album",
            "song": "single",
            "television": "tv",
            "series": "tv",
            "film": "movie",
        }
        normalized = mapping.get(work_type, work_type)
        return normalized if normalized in VALID_WORK_TYPES else "movie"

    def _normalize_relation_type(self, relation_type: str) -> str:
        """Map spider relation types to the current MySQL enum."""
        mapping = {
            "acted_in": "COLLABORATED_WITH",
            "directed": "COLLABORATED_WITH",
            "wrote": "COLLABORATED_WITH",
            "produced": "COLLABORATED_WITH",
            "composed": "COLLABORATED_WITH",
            "sang": "COLLABORATED_WITH",
            "related_to": "FRIEND",
            "married_to": "MARRIED_TO",
            "parent_of": "RELATIVE",
            "child_of": "RELATIVE",
            "sibling_of": "RELATIVE",
        }
        if relation_type in {"MARRIED_TO", "COLLABORATED_WITH", "MENTOR_OF", "RELATIVE", "FRIEND"}:
            return relation_type
        return mapping.get(relation_type, "COLLABORATED_WITH")

    def _upsert_source_stats(self, spider):
        """Persist daily crawl source statistics collected by Scrapy."""
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
        valid_records = (
            self.stats["persons_inserted"]
            + self.stats["works_inserted"]
            + self.stats["relations_inserted"]
        )
        duration = int(get_value("elapsed_time_seconds", 0) or 0)

        sql = """
            INSERT INTO crawl_source_stats (
                source_id, stat_date, total_requests, success_requests, failed_requests,
                timeout_requests, rate_limited_requests, persons_extracted, works_extracted,
                relations_extracted, valid_records, duplicate_records, total_duration,
                created_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s
            )
            ON DUPLICATE KEY UPDATE
                total_requests = total_requests + VALUES(total_requests),
                success_requests = success_requests + VALUES(success_requests),
                failed_requests = failed_requests + VALUES(failed_requests),
                timeout_requests = timeout_requests + VALUES(timeout_requests),
                rate_limited_requests = rate_limited_requests + VALUES(rate_limited_requests),
                persons_extracted = persons_extracted + VALUES(persons_extracted),
                works_extracted = works_extracted + VALUES(works_extracted),
                relations_extracted = relations_extracted + VALUES(relations_extracted),
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
            self.stats["persons_inserted"],
            self.stats["works_inserted"],
            self.stats["relations_inserted"],
            valid_records,
            0,
            duration,
            datetime.utcnow(),
        )
        self.cursor.execute(sql, params)
        self._update_source_totals(source_id, total_requests, success_requests, failed_requests)
        logger.info("Upserted crawl_source_stats for source_id=%s", source_id)

    def _resolve_source_id(self, spider):
        """Resolve crawl_sources.id from spider kwargs or source code."""
        source_id = getattr(spider, "source_id", None)
        if source_id:
            return source_id

        source_code = getattr(spider, "source", None)
        if not source_code:
            return None

        aliases = {
            "wikipedia": "wikipedia_zh",
            "douban": "douban_movie",
            "baike": "baidu_baike",
        }
        candidates = [source_code, aliases.get(source_code)]
        placeholders = ", ".join(["%s"] * len([candidate for candidate in candidates if candidate]))
        if not placeholders:
            return None

        sql = f"SELECT id FROM crawl_sources WHERE code IN ({placeholders}) LIMIT 1"
        self.cursor.execute(sql, tuple(candidate for candidate in candidates if candidate))
        row = self.cursor.fetchone()
        if row:
            return row["id"]
        return self._create_default_source(source_code)

    def _create_default_source(self, source_code):
        """Create a default crawl source row when legacy databases lack one."""
        defaults = {
            "baike": ("百度百科", "baidu_baike", "encyclopedia", "https://baike.baidu.com/"),
            "douban": ("豆瓣电影", "douban_movie", "social", "https://movie.douban.com/"),
            "wikipedia": ("维基百科（中文）", "wikipedia_zh", "encyclopedia", "https://zh.wikipedia.org/wiki/"),
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
                source_id,
                name,
                code,
                source_type,
                base_url,
                json.dumps({}, ensure_ascii=False),
                "active",
                "healthy",
                1.0,
                1000,
                5,
                0,
                0,
                0,
                datetime.utcnow(),
                datetime.utcnow(),
            ),
        )
        self.cursor.execute("SELECT id FROM crawl_sources WHERE code = %s LIMIT 1", (code,))
        row = self.cursor.fetchone()
        return row["id"] if row else source_id

    def _update_source_totals(self, source_id, total_requests, success_requests, failed_requests):
        """Update aggregate counters on crawl_sources."""
        sql = """
            UPDATE crawl_sources
            SET total_requests = total_requests + %s,
                total_success = total_success + %s,
                total_failed = total_failed + %s,
                updated_at = %s
            WHERE id = %s
        """
        self.cursor.execute(
            sql,
            (
                total_requests,
                success_requests,
                failed_requests,
                datetime.utcnow(),
                source_id,
            ),
        )


class Neo4jPipeline:
    """
    Pipeline for storing graph relationships in Neo4j.
    
    Creates nodes and edges for persons and works.
    """

    def __init__(self, neo4j_uri, neo4j_user, neo4j_password):
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.driver = None

    @classmethod
    def from_crawler(cls, crawler):
        """Create pipeline instance from crawler settings."""
        return cls(
            neo4j_uri=crawler.settings.get("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=crawler.settings.get("NEO4J_USER", "neo4j"),
            neo4j_password=crawler.settings.get("NEO4J_PASSWORD", "starmap123"),
        )

    def open_spider(self, spider):
        """Open Neo4j connection."""
        try:
            from neo4j import GraphDatabase
            self.driver = GraphDatabase.driver(
                self.neo4j_uri,
                auth=(self.neo4j_user, self.neo4j_password)
            )
            logger.info("Neo4j connection opened")
        except ImportError:
            logger.warning("Neo4j driver not installed, skipping graph storage")
        except Exception as e:
            logger.error(f"Failed to open Neo4j connection: {e}")

    def close_spider(self, spider):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")

    def process_item(self, item, spider):
        """Process item and store in Neo4j."""
        if not self.driver:
            return item
        
        try:
            if isinstance(item, PersonItem):
                self._create_person_node(item)
            elif isinstance(item, WorkItem):
                self._create_work_node(item)
            elif isinstance(item, RelationItem):
                self._create_relation_edge(item)
            
            return item
            
        except Exception as e:
            logger.error(f"Failed to store item in Neo4j: {e}")
            return item

    def _create_person_node(self, item: PersonItem):
        """Create or update person node in Neo4j."""
        with self.driver.session() as session:
            session.run("""
                MERGE (p:Person {id: $id})
                SET p.name = $name,
                    p.name_en = $name_en,
                    p.avatar = $avatar,
                    p.gender = $gender,
                    p.birth_date = $birth_date,
                    p.nationality = $nationality,
                    p.summary = $summary,
                    p.source = $source,
                    p.updated_at = datetime()
            """, {
                "id": item.get("id"),
                "name": item.get("name"),
                "name_en": item.get("name_en"),
                "avatar": item.get("avatar"),
                "gender": item.get("gender"),
                "birth_date": item.get("birth_date"),
                "nationality": item.get("nationality"),
                "summary": item.get("summary"),
                "source": item.get("source"),
            })

    def _create_work_node(self, item: WorkItem):
        """Create or update work node in Neo4j."""
        with self.driver.session() as session:
            session.run("""
                MERGE (w:Work {id: $id})
                SET w.title = $title,
                    w.type = $type,
                    w.release_date = $release_date,
                    w.rating = $rating,
                    w.source = $source,
                    w.updated_at = datetime()
            """, {
                "id": item.get("id"),
                "title": item.get("title"),
                "type": item.get("type"),
                "release_date": item.get("release_date"),
                "rating": item.get("rating"),
                "source": item.get("source"),
            })

    def _create_relation_edge(self, item: RelationItem):
        """Create relationship edge in Neo4j."""
        with self.driver.session() as session:
            session.run("""
                MATCH (a {id: $source_id})
                MATCH (b {id: $target_id})
                MERGE (a)-[r:RELATES {type: $relation_type}]->(b)
                SET r.role = $role,
                    r.source = $source,
                    r.updated_at = datetime()
            """, {
                "source_id": item.get("source_id"),
                "target_id": item.get("target_id"),
                "relation_type": item.get("relation_type"),
                "role": item.get("role"),
                "source": item.get("source"),
            })
