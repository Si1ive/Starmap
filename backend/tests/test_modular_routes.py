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
