from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_DIR / "backend"


def test_backend_runtime_declares_alembic_dependency():
    requirements = (BACKEND_DIR / "requirements.txt").read_text(encoding="utf-8")

    assert any(
        line.strip().lower().startswith("alembic==")
        for line in requirements.splitlines()
    )


def test_compose_bootstraps_baseline_schema_before_alembic():
    compose = (PROJECT_DIR / "docker-compose.podman.yml").read_text(
        encoding="utf-8"
    )

    assert (
        "./backend/scripts/init_mysql.sql:"
        "/docker-entrypoint-initdb.d/01-init-mysql.sql:ro"
    ) in compose
    assert (
        "./backend/scripts/init_408_tables.sql:"
        "/docker-entrypoint-initdb.d/02-init-408.sql:ro"
    ) in compose
    assert "alembic -c alembic.ini upgrade head && uvicorn" in compose


def test_application_no_longer_contains_legacy_runtime_migrator():
    main_source = (BACKEND_DIR / "app" / "main.py").read_text(encoding="utf-8")

    assert "app.tasks.migrate" not in main_source
    assert not (BACKEND_DIR / "app" / "tasks" / "migrate.py").exists()
