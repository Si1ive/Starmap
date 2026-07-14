"""Catalog chapter link module compatibility tests."""

from app.modules.catalog.chapter_link_service import ChapterLinkService
from app.services.chapter_link_service import ChapterLinkService as LegacyChapterLinkService


def test_legacy_chapter_link_service_exports_catalog_implementation():
    assert LegacyChapterLinkService is ChapterLinkService
