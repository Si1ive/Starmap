"""Catalog chapter mapping module compatibility tests."""

from app.modules.catalog.chapter_mapping_service import (
    CanonicalChapterService,
    ChapterMappingService,
)
from app.services.chapter_mapping_service import (
    CanonicalChapterService as LegacyCanonicalChapterService,
)
from app.services.chapter_mapping_service import (
    ChapterMappingService as LegacyChapterMappingService,
)


def test_legacy_chapter_mapping_service_exports_catalog_implementations():
    assert LegacyCanonicalChapterService is CanonicalChapterService
    assert LegacyChapterMappingService is ChapterMappingService
