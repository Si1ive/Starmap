import importlib.util
import io
from pathlib import Path
from unittest.mock import Mock

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

    assert scripts.get_heads() == ["20260728_agent_llm_audit"]


def test_vector_recall_trace_migration_adds_correlation_fields():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = backend_dir / "alembic" / "versions" / "20260728_vector_recall_trace.py"
    spec = importlib.util.spec_from_file_location("vector_recall_trace_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output}
    )
    migration.op = Operations(context)
    migration.upgrade()
    ddl = output.getvalue()
    assert "ADD COLUMN trace_id VARCHAR(64)" in ddl
    assert "ADD COLUMN phase VARCHAR(32)" in ddl
    assert "idx_vec_recall_trace" in ddl


def test_agent_llm_audit_migration_adds_run_correlation():
    backend_dir = Path(__file__).resolve().parents[1]
    path = backend_dir / "alembic" / "versions" / "20260728_agent_llm_audit.py"
    spec = importlib.util.spec_from_file_location("agent_llm_audit_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(), opts={"as_sql": True, "output_buffer": output}
    )
    migration.op = Operations(context)
    migration.upgrade()
    ddl = output.getvalue()
    assert "ADD COLUMN trace_id VARCHAR(64)" in ddl
    assert "ADD COLUMN run_id VARCHAR(32)" in ddl
    assert "idx_llm_calls_run" in ddl


def test_user_identity_migration_renders_mysql_ddl():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = backend_dir / "alembic" / "versions" / "20260716_user_identity.py"
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
        backend_dir / "alembic" / "versions" / "20260723_agent_conversation_timeline.py"
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


def test_agent_model_configs_migration_renders_mysql_ddl_and_legacy_backfill():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = (
        backend_dir / "alembic" / "versions" / "20260723_agent_model_configs.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_model_configs_migration",
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

    assert "CREATE TABLE agent_model_configs" in ddl
    assert "uk_agent_model_display_name" in ddl
    assert "uk_agent_model_default_slot" in ddl
    assert "INSERT INTO agent_model_configs" in ddl
    assert "FROM system_configs" in ddl


def test_agent_unlimited_tokens_migration_makes_limit_nullable():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = (
        backend_dir / "alembic" / "versions" / "20260724_agent_unlimited_tokens.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_unlimited_tokens_migration",
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

    assert "ALTER TABLE agent_model_configs MODIFY max_tokens INTEGER NULL" in ddl


def test_agent_activity_migration_adds_public_event_type():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = backend_dir / "alembic" / "versions" / "20260725_agent_activity.py"
    spec = importlib.util.spec_from_file_location("agent_activity_migration", migration_path)
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

    assert "workflow.activity.updated" in output.getvalue()


def test_agent_memory_foundation_migration_renders_mysql_ddl():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = (
        backend_dir / "alembic" / "versions" / "20260726_agent_memory_foundation.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_memory_foundation_migration",
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

    assert "CREATE TABLE agent_thread_memory_states" in ddl
    assert "CREATE TABLE agent_memory_events" in ddl
    assert "CREATE TABLE agent_memory_snapshots" in ddl
    assert "CREATE TABLE agent_memory_snapshot_items" in ddl
    assert "CREATE TABLE agent_memory_update_outbox" in ddl
    assert "CREATE TABLE user_learning_mastery" in ddl
    assert "CREATE TABLE agent_conversation_summaries" in ddl
    assert "CREATE TABLE agent_memory_items" in ddl
    assert "uk_agent_thread_memory_thread" in ddl
    assert "uk_agent_memory_event_idempotency" in ddl
    assert "uk_user_learning_mastery" in ddl


def test_memory_outbox_idempotency_migration_renders_mysql_ddl():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = (
        backend_dir / "alembic" / "versions" / "20260726_memory_outbox_unique.py"
    )
    spec = importlib.util.spec_from_file_location(
        "memory_outbox_idempotency_migration",
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
    assert "ALTER TABLE agent_memory_update_outbox" in ddl
    assert "uk_agent_memory_outbox_run_event" in ddl


def test_agent_preference_candidate_migration_renders_mysql_ddl():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = (
        backend_dir / "alembic" / "versions" / "20260727_preference_candidates.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_preference_candidate_migration",
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
    assert "CREATE TABLE agent_preference_candidates" in ddl
    assert "uk_agent_preference_candidate_source_key" in ddl
    assert "pending" in ddl
    assert "approved" in ddl
    assert "rejected" in ddl


def test_thread_memory_delete_migration_renders_mysql_ddl():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = (
        backend_dir / "alembic" / "versions" / "20260727_thread_memory_delete.py"
    )
    spec = importlib.util.spec_from_file_location(
        "thread_memory_delete_migration",
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

    assert "MODIFY run_id VARCHAR(32) NULL" in ddl
    assert "ADD COLUMN task_key VARCHAR(128)" in ddl
    assert "uk_agent_memory_outbox_task_key" in ddl


def test_memory_outbox_error_migration_adds_safe_failure_summary():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = (
        backend_dir / "alembic" / "versions" / "20260727_memory_outbox_error.py"
    )
    spec = importlib.util.spec_from_file_location(
        "memory_outbox_error_migration",
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
    assert "ADD COLUMN last_error_message TEXT" in ddl


def test_memory_trace_migration_creates_before_after_state_table():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = backend_dir / "alembic" / "versions" / "20260727_memory_trace.py"
    spec = importlib.util.spec_from_file_location("memory_trace_migration", migration_path)
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
    assert "CREATE TABLE agent_memory_traces" in ddl
    assert "before_json JSON NOT NULL" in ddl
    assert "after_json JSON NOT NULL" in ddl
    assert "idx_agent_memory_trace_run" in ddl


def _load_agent_parent_repair_migration():
    backend_dir = Path(__file__).resolve().parents[1]
    migration_path = (
        backend_dir / "alembic" / "versions" / "20260723_repair_agent_parent.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_parent_repair_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None

    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_agent_parent_repair_migration_restores_missing_schema(monkeypatch):
    migration = _load_agent_parent_repair_migration()
    migration.op = Mock()
    bind = Mock()
    migration.op.get_bind.return_value = bind

    initial_inspector = Mock()
    initial_inspector.get_columns.return_value = [{"name": "root_run_id"}]
    refreshed_inspector = Mock()
    refreshed_inspector.get_indexes.return_value = []
    refreshed_inspector.get_foreign_keys.return_value = []
    monkeypatch.setattr(
        migration.sa,
        "inspect",
        Mock(side_effect=[initial_inspector, refreshed_inspector]),
    )

    migration.upgrade()

    migration.op.add_column.assert_called_once()
    migration.op.create_index.assert_called_once_with(
        "idx_agent_run_parent",
        "agent_runs",
        ["parent_run_id"],
    )
    migration.op.create_foreign_key.assert_called_once_with(
        "fk_agent_run_parent",
        "agent_runs",
        "agent_runs",
        ["parent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def test_agent_parent_repair_migration_is_idempotent(monkeypatch):
    migration = _load_agent_parent_repair_migration()
    migration.op = Mock()
    bind = Mock()
    migration.op.get_bind.return_value = bind

    initial_inspector = Mock()
    initial_inspector.get_columns.return_value = [{"name": "parent_run_id"}]
    refreshed_inspector = Mock()
    refreshed_inspector.get_indexes.return_value = [{"name": "idx_agent_run_parent"}]
    refreshed_inspector.get_foreign_keys.return_value = [
        {"name": "fk_agent_run_parent"}
    ]
    monkeypatch.setattr(
        migration.sa,
        "inspect",
        Mock(side_effect=[initial_inspector, refreshed_inspector]),
    )

    migration.upgrade()

    migration.op.add_column.assert_not_called()
    migration.op.create_index.assert_not_called()
    migration.op.create_foreign_key.assert_not_called()
