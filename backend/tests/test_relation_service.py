"""Knowledge relation module compatibility tests."""

from app.modules.retrieval.relation_service import RelationService
from app.services.relation_service import RelationService as LegacyRelationService


def test_legacy_relation_service_exports_retrieval_implementation():
    assert LegacyRelationService is RelationService


def test_relation_string_similarity_keeps_existing_jaccard_behavior():
    service = RelationService(None)

    assert service._string_similarity("进程调度", "进程调度") == 1.0
    assert service._string_similarity("", "进程调度") == 0.0
    assert 0 < service._string_similarity("进程调度", "进程管理") < 1
