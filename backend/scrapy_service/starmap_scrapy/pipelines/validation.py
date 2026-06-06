"""
Validation Pipeline for Scrapy Items.

Validates scraped items before storing them to the database.
"""

import logging
from datetime import datetime
from typing import Optional

from scrapy.exceptions import DropItem

from starmap_scrapy.items import PersonItem, WorkItem, RelationItem

logger = logging.getLogger(__name__)


class ValidationPipeline:
    """
    Validate scraped items.
    
    Checks required fields, data types, and value ranges.
    Drops invalid items and logs warnings.
    """

    # Required fields for each item type
    REQUIRED_FIELDS = {
        "PersonItem": ["name"],
        "WorkItem": ["title", "type"],
        "RelationItem": ["source_id", "target_id", "relation_type"],
    }

    # Valid values for enum fields
    VALID_GENDERS = {"male", "female", "unknown"}
    VALID_WORK_TYPES = {"movie", "tv", "album", "single", "book"}
    VALID_STATUSES = {"active", "pending", "deleted"}

    def process_item(self, item, spider):
        """Process and validate item."""
        item_type = type(item).__name__
        
        try:
            if isinstance(item, PersonItem):
                self._validate_person(item)
            elif isinstance(item, WorkItem):
                self._validate_work(item)
            elif isinstance(item, RelationItem):
                self._validate_relation(item)
            else:
                logger.warning(f"Unknown item type: {item_type}")
                return item
            
            # Add validation timestamp
            item["updated_at"] = datetime.utcnow().isoformat()
            
            logger.debug(f"Validated {item_type}: {item.get('name', item.get('title', 'unknown'))}")
            return item
            
        except DropItem as e:
            logger.warning(f"Dropped invalid {item_type}: {e}")
            raise
        except Exception as e:
            logger.error(f"Validation error for {item_type}: {e}")
            raise DropItem(f"Validation error: {e}")

    def _validate_person(self, item: PersonItem):
        """Validate person item."""
        # Check required fields
        if not item.get("name"):
            raise DropItem("Person name is required")
        
        # Validate name length
        name = item.get("name", "")
        if len(name) > 100:
            item["name"] = name[:100]
            logger.warning(f"Truncated person name to 100 chars: {name}")
        
        # Validate gender
        gender = item.get("gender")
        if gender and gender not in self.VALID_GENDERS:
            logger.warning(f"Invalid gender '{gender}', setting to 'unknown'")
            item["gender"] = "unknown"
        
        # Validate height
        height = item.get("height")
        if height is not None:
            try:
                height_val = float(height)
                if height_val < 0 or height_val > 300:
                    logger.warning(f"Invalid height {height_val}, removing")
                    item["height"] = None
                else:
                    item["height"] = height_val
            except (ValueError, TypeError):
                item["height"] = None
        
        # Validate categories
        categories = item.get("categories", [])
        if isinstance(categories, str):
            categories = [c.strip() for c in categories.split(",") if c.strip()]
            item["categories"] = categories
        
        # Set default status
        if not item.get("status"):
            item["status"] = "pending"

    def _validate_work(self, item: WorkItem):
        """Validate work item."""
        # Check required fields
        if not item.get("title"):
            raise DropItem("Work title is required")
        
        if not item.get("type"):
            raise DropItem("Work type is required")
        
        # Validate type
        work_type = item.get("type")
        if work_type not in self.VALID_WORK_TYPES:
            raise DropItem(f"Invalid work type: {work_type}")
        
        # Validate rating
        rating = item.get("rating")
        if rating is not None:
            try:
                rating_val = float(rating)
                if rating_val < 0 or rating_val > 10:
                    logger.warning(f"Invalid rating {rating_val}, removing")
                    item["rating"] = None
                else:
                    item["rating"] = rating_val
            except (ValueError, TypeError):
                item["rating"] = None
        
        # Validate lists
        list_fields = ["director", "actors", "artist", "track_list", "author"]
        for field in list_fields:
            value = item.get(field, [])
            if isinstance(value, str):
                item[field] = [v.strip() for v in value.split(",") if v.strip()]
            elif not isinstance(value, list):
                item[field] = []
        
        # Set default status
        if not item.get("status"):
            item["status"] = "pending"

    def _validate_relation(self, item: RelationItem):
        """Validate relation item."""
        # Check required fields
        for field in ["source_id", "target_id", "relation_type"]:
            if not item.get(field):
                raise DropItem(f"Relation {field} is required")
        
        # Validate relation type
        valid_types = {
            "acted_in", "directed", "wrote", "produced",
            "composed", "sang", "related_to", "married_to",
            "parent_of", "child_of", "sibling_of",
        }
        if item.get("relation_type") not in valid_types:
            logger.warning(f"Unusual relation type: {item.get('relation_type')}")
