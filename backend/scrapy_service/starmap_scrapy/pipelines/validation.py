"""
Validation Pipeline for Scrapy Items.

Validates scraped items before storing them to the database.
"""

import logging
from datetime import datetime

from scrapy.exceptions import DropItem

from starmap_scrapy.items import FileDownloadItem, KnowledgePointItem, QuestionItem

logger = logging.getLogger(__name__)


class ValidationPipeline:
    """Validate scraped items. Drops invalid items and logs warnings."""

    def process_item(self, item, spider):
        """Process and validate item."""
        item_type = type(item).__name__

        try:
            if isinstance(item, FileDownloadItem):
                self._validate_file_download(item)
            elif isinstance(item, KnowledgePointItem):
                self._validate_knowledge_point(item)
            elif isinstance(item, QuestionItem):
                self._validate_question(item)
            else:
                return item

            item["updated_at"] = datetime.utcnow().isoformat()
            return item

        except DropItem:
            raise
        except Exception as e:
            logger.error(f"Validation error for {item_type}: {e}")
            raise DropItem(f"Validation error: {e}")

    def _validate_file_download(self, item: FileDownloadItem):
        """Validate file download item."""
        if not item.get("file_path"):
            raise DropItem("file_path is required")
        if not item.get("file_name"):
            raise DropItem("file_name is required")

    def _validate_knowledge_point(self, item: KnowledgePointItem):
        """Validate knowledge point item."""
        if not item.get("title"):
            raise DropItem("Knowledge point title is required")
        if not item.get("content"):
            raise DropItem("Knowledge point content is required")

    def _validate_question(self, item: QuestionItem):
        """Validate question item."""
        if not item.get("content"):
            raise DropItem("Question content is required")
        if not item.get("answer"):
            raise DropItem("Question answer is required")
