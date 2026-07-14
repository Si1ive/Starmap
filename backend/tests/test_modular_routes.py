"""Contract tests for routes moved out of the legacy admin module."""

from app.main import app


def _routes_by_path():
    return {
        route.path: route
        for route in app.routes
        if hasattr(route, "path") and hasattr(route, "endpoint")
    }


def _methods_by_path():
    methods = {}
    for route in app.routes:
        if not hasattr(route, "methods"):
            continue
        methods.setdefault(route.path, set()).update(route.methods)
    return methods


def test_catalog_routes_keep_existing_paths_and_methods():
    routes = _routes_by_path()

    subjects = routes["/api/v1/admin/subjects"]
    chapters = routes["/api/v1/admin/subjects/{subject_id}/chapters"]
    canonical_chapters = routes["/api/v1/admin/canonical-chapters"]

    assert "GET" in subjects.methods
    assert "GET" in chapters.methods
    assert "GET" in canonical_chapters.methods


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


def test_public_chat_routes_are_owned_by_chat_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/chat",
        "/api/v1/chat/{session_id}/history",
    ):
        assert routes[path].endpoint.__module__ == "app.modules.chat.router"


def test_admin_conversation_routes_are_owned_by_chat_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/conversations",
        "/api/v1/admin/conversations/{conversation_id}",
    ):
        assert routes[path].endpoint.__module__ == "app.modules.chat.admin_router"

    methods = _methods_by_path()
    assert {"GET"} <= methods["/api/v1/admin/conversations"]
    assert {"GET", "DELETE"} <= methods[
        "/api/v1/admin/conversations/{conversation_id}"
    ]


def test_dashboard_routes_are_owned_by_dashboard_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/dashboard/stats",
        "/api/v1/admin/dashboard/charts",
    ):
        route = routes[path]
        assert route.endpoint.__module__ == "app.modules.dashboard.router"
        assert "GET" in route.methods


def test_settings_routes_are_owned_by_operations_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/settings",
        "/api/v1/admin/settings/pdf-parser/history",
        "/api/v1/admin/settings/llm/{kind}/status",
        "/api/v1/admin/settings/llm/{kind}/test",
    ):
        assert (
            routes[path].endpoint.__module__ == "app.modules.operations.settings_router"
        )


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
    assert (
        routes["/api/v1/admin/canonical-chapters"].endpoint.__module__
        == "app.modules.catalog.router"
    )
    assert (
        routes["/api/v1/admin/canonical-chapters/init"].endpoint.__module__
        == "app.modules.catalog.router"
    )


def test_section_review_routes_are_owned_by_catalog_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/review/sections",
        "/api/v1/admin/review/sections/{mapping_id}",
        "/api/v1/admin/review/sections/batch-delete",
    ):
        assert (
            routes[path].endpoint.__module__
            == "app.modules.catalog.section_review_router"
        )

    post_paths = [
        route.path
        for route in app.routes
        if hasattr(route, "methods") and "POST" in route.methods
    ]
    assert post_paths.index(
        "/api/v1/admin/review/sections/batch-delete"
    ) < post_paths.index("/api/v1/admin/review/sections/{mapping_id}")


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


def test_relation_review_routes_are_owned_by_content_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/review/relations",
        "/api/v1/admin/review/relations/{relation_id}",
        "/api/v1/admin/review/relations/batch-delete",
        "/api/v1/admin/review/stats",
    ):
        assert (
            routes[path].endpoint.__module__
            == "app.modules.content.relation_review_router"
        )

    post_paths = [
        route.path
        for route in app.routes
        if hasattr(route, "methods") and "POST" in route.methods
    ]
    assert post_paths.index(
        "/api/v1/admin/review/relations/batch-delete"
    ) < post_paths.index("/api/v1/admin/review/relations/{relation_id}")


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


def test_crawler_routes_are_owned_by_crawler_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/crawler/config",
        "/api/v1/admin/crawler/tasks",
        "/api/v1/admin/crawler/tasks/{task_id}/start",
        "/api/v1/admin/crawler/tasks/{task_id}/stop",
        "/api/v1/admin/crawler/tasks/{task_id}",
        "/api/v1/admin/crawler/sources",
        "/api/v1/admin/crawler/sources/defaults",
        "/api/v1/admin/crawler/sources/{source_id}",
        "/api/v1/admin/crawler/sources/{source_id}/health",
        "/api/v1/admin/crawler/sources/{source_id}/stats",
        "/api/v1/admin/crawler/stats/overview",
        "/api/v1/admin/crawler/stats/sources",
        "/api/v1/admin/crawler/stats/trend",
        "/api/v1/admin/crawler/stats/file-types",
        "/api/v1/admin/crawler/stats/suggestions",
        "/api/v1/admin/crawler/scrapy/status",
        "/api/v1/admin/crawler/schedules",
        "/api/v1/admin/crawler/schedules/{schedule_id}",
        "/api/v1/admin/crawler/schedules/{schedule_id}/toggle",
        "/api/v1/admin/crawler/schedules/{schedule_id}/runs",
        "/api/v1/admin/crawler/logs",
        "/api/v1/admin/crawler/logs/export",
        "/api/v1/admin/crawler/file-logs",
        "/api/v1/admin/crawler/file-logs/repos",
        "/api/v1/admin/crawler/file-logs/retry",
        "/api/v1/admin/crawler/logs/analysis",
        "/api/v1/admin/crawler/logs/stream",
    ):
        assert routes[path].endpoint.__module__ == "app.modules.crawler.router"


def test_downloaded_file_routes_are_owned_by_crawler_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/files/downloaded",
        "/api/v1/admin/files/downloaded/{file_id}",
        "/api/v1/admin/files/downloaded/{file_id}/preview",
    ):
        assert (
            routes[path].endpoint.__module__
            == "app.modules.crawler.file_router"
        )


def test_legacy_pdf_ingest_routes_are_owned_by_crawler_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/knowledge/ingest",
        "/api/v1/admin/knowledge/ingest/tasks",
    ):
        assert (
            routes[path].endpoint.__module__
            == "app.modules.crawler.pdf_ingest_router"
        )


def test_crawler_routes_keep_existing_http_methods():
    methods = _methods_by_path()
    expected = {
        "/api/v1/admin/crawler/config": {"GET", "PUT"},
        "/api/v1/admin/crawler/tasks": {"GET", "POST"},
        "/api/v1/admin/crawler/tasks/{task_id}": {"DELETE"},
        "/api/v1/admin/crawler/sources": {"GET", "POST"},
        "/api/v1/admin/crawler/sources/{source_id}": {"GET", "PUT", "DELETE"},
        "/api/v1/admin/crawler/schedules": {"GET", "POST"},
        "/api/v1/admin/crawler/schedules/{schedule_id}": {
            "GET",
            "PUT",
            "DELETE",
        },
        "/api/v1/admin/crawler/logs": {"GET"},
        "/api/v1/admin/crawler/file-logs": {"GET"},
        "/api/v1/admin/crawler/file-logs/retry": {"POST"},
    }

    for path, expected_methods in expected.items():
        assert expected_methods <= methods[path]


def test_settings_routes_keep_existing_http_methods():
    methods = _methods_by_path()

    assert {"GET", "PUT"} <= methods["/api/v1/admin/settings"]
    assert {"GET"} <= methods["/api/v1/admin/settings/pdf-parser/history"]
    assert {"GET"} <= methods["/api/v1/admin/settings/llm/{kind}/status"]
    assert {"POST"} <= methods["/api/v1/admin/settings/llm/{kind}/test"]


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
        "/api/v1/admin/relations/build",
    ):
        assert routes[path].endpoint.__module__ == "app.modules.retrieval.router"


def test_monitor_routes_are_owned_by_monitoring_module():
    routes = _routes_by_path()

    for path in (
        "/api/v1/admin/monitor/api",
        "/api/v1/admin/monitor/database",
        "/api/v1/admin/monitor/errors",
        "/api/v1/admin/monitor/logs",
        "/api/v1/admin/monitor/logs/stats",
        "/api/v1/admin/monitor/logs/archive",
        "/api/v1/admin/monitor/system",
        "/api/v1/admin/monitor/llm-calls",
        "/api/v1/admin/monitor/llm-calls/stats",
        "/api/v1/admin/monitor/llm-calls/{call_id}",
        "/api/v1/admin/monitor/vector-recalls",
        "/api/v1/admin/monitor/vector-recalls/stats",
    ):
        assert routes[path].endpoint.__module__ == "app.modules.monitoring.router"


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
