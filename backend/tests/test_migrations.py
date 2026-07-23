import importlib.util
import io
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import mysql


def test_revision_ids_fit_default_alembic_version_column():
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    oversized = [
        revision.revision
        for revision in scripts.walk_revisions()
        if len(revision.revision) > 32
    ]

    assert oversized == []


def test_migration_graph_has_single_head():
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["20260723_agent_thread_events"]


def test_user_identity_migration_renders_mysql_ddl():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = (
        backend_dir / "alembic" / "versions" / "20260716_user_identity.py"
    )
    spec = importlib.util.spec_from_file_location(
        "user_identity_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None

    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    output = io.StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)
    migration.upgrade()
    ddl = output.getvalue()

    assert "CREATE TABLE users" in ddl
    assert "CREATE TABLE auth_sessions" in ddl
    assert "DATETIME(6)" in ddl


def test_agent_timeline_migration_renders_mysql_ddl():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = (
        backend_dir
        / "alembic"
        / "versions"
        / "20260723_agent_conversation_timeline.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_conversation_timeline_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None

    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    output = io.StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)
    migration.upgrade()
    ddl = output.getvalue()

    assert "CREATE TABLE agent_messages" in ddl
    assert "CREATE TABLE agent_thread_items" in ddl
    assert "ADD COLUMN last_item_sequence BIGINT" in ddl
    assert "run.failed" in ddl


def test_agent_thread_events_migration_renders_mysql_ddl():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = (
        backend_dir / "alembic" / "versions" / "20260723_agent_thread_events.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_thread_events_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None

    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    output = io.StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)
    migration.upgrade()
    ddl = output.getvalue()

    assert "CREATE TABLE agent_thread_events" in ddl
    assert "timeline.item.created" in ddl
    assert "workflow.updated" in ddl
