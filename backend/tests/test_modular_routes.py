"""Contract tests for routes moved out of the legacy admin module."""

from app.main import app


def _routes_by_path():
    return {
        route.path: route
        for route in app.routes
        if hasattr(route, "path") and hasattr(route, "endpoint")
    }


def test_catalog_routes_keep_existing_paths_and_methods():
    routes = _routes_by_path()

    subjects = routes["/api/v1/admin/subjects"]
    chapters = routes["/api/v1/admin/subjects/{subject_id}/chapters"]

    assert "GET" in subjects.methods
    assert "GET" in chapters.methods


def test_auth_and_user_routes_are_owned_by_operations_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/auth/login",
        "/api/v1/admin/auth/logout",
        "/api/v1/admin/auth/me",
        "/api/v1/admin/users",
        "/api/v1/admin/users/{user_id}",
    ):
        assert routes[path].endpoint.__module__ == "app.modules.operations.router"


def test_catalog_routes_are_owned_by_catalog_module():
    routes = _routes_by_path()

    assert (
        routes["/api/v1/admin/subjects"].endpoint.__module__
        == "app.modules.catalog.router"
    )
    assert (
        routes["/api/v1/admin/subjects/{subject_id}/chapters"].endpoint.__module__
        == "app.modules.catalog.router"
    )


def test_content_routes_are_owned_by_content_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/knowledge/points",
        "/api/v1/admin/questions",
        "/api/v1/admin/review/knowledge",
        "/api/v1/admin/review/questions",
        "/api/v1/admin/enrichment/document/{document_id}",
        "/api/v1/admin/enrichment/question/{question_id}",
        "/api/v1/admin/enrichment/knowledge/{kp_id}",
    ):
        assert routes[path].endpoint.__module__ == "app.modules.content.router"


def test_corpus_file_and_parse_routes_are_owned_by_corpus_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/corpus/files/scan",
        "/api/v1/admin/corpus/files/register",
        "/api/v1/admin/corpus/files/register-by-download",
        "/api/v1/admin/corpus/files/upload",
        "/api/v1/admin/corpus/files",
        "/api/v1/admin/corpus/files/{file_id}",
        "/api/v1/admin/corpus/files/{file_id}/parse",
        "/api/v1/admin/corpus/files/batch-delete",
        "/api/v1/admin/corpus/parse-runs",
        "/api/v1/admin/corpus/parse-runs/{run_id}",
        "/api/v1/admin/corpus/documents/{document_id}",
    ):
        assert routes[path].endpoint.__module__ == "app.modules.corpus.router"


def test_corpus_document_workflow_routes_are_owned_by_corpus_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/corpus/documents/{document_id}/blocks",
        "/api/v1/admin/corpus/documents/{document_id}/sections",
        "/api/v1/admin/corpus/documents/{document_id}/page-analysis",
        "/api/v1/admin/corpus/documents/{document_id}/extract-sections",
        "/api/v1/admin/corpus/documents/{document_id}/map-chapters",
        "/api/v1/admin/corpus/documents/{document_id}/section-mappings",
        "/api/v1/admin/corpus/documents/{document_id}/chapter-diagnostics",
        "/api/v1/admin/corpus/documents/{document_id}/content-overview",
        "/api/v1/admin/corpus/documents/{document_id}/extract-entities",
        "/api/v1/admin/corpus/documents/{document_id}/extraction-status",
        "/api/v1/admin/corpus/documents/{document_id}/entities/{entity_type}/{entity_id}/reextract",
        "/api/v1/admin/corpus/documents/{document_id}/entities/{entity_type}/{entity_id}/reextraction-status",
    ):
        assert routes[path].endpoint.__module__ == "app.modules.corpus.router"


def test_retrieval_routes_are_owned_by_retrieval_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/segments/build",
        "/api/v1/admin/segments/build/knowledge",
        "/api/v1/admin/segments/build/questions",
        "/api/v1/admin/segments/build/chapters",
        "/api/v1/admin/search",
        "/api/v1/admin/search/with-relations",
        "/api/v1/admin/search/with-outline",
        "/api/v1/admin/search/dual-path",
        "/api/v1/admin/search/chapter-expansion",
    ):
        assert routes[path].endpoint.__module__ == "app.modules.retrieval.router"


def test_application_has_no_duplicate_method_path_pairs():
    seen = set()
    duplicates = []

    for route in app.routes:
        if not hasattr(route, "methods"):
            continue
        for method in route.methods:
            key = (method, route.path)
            if key in seen:
                duplicates.append(key)
            seen.add(key)

    assert duplicates == []
