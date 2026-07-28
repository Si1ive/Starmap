"""Validate that the connected database matches the Alembic migration graph."""

from pathlib import Path
from typing import Iterable

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_DIR = Path(__file__).resolve().parents[3]
AGENT_RUN_WORKER_COLUMNS = frozenset({"parent_run_id", "root_run_id"})
AGENT_REQUIRED_TABLES = frozenset(
    {
        "agent_model_configs",
        "agent_thread_memory_states",
        "agent_memory_events",
        "agent_memory_snapshots",
        "agent_memory_snapshot_items",
        "agent_memory_traces",
        "agent_memory_update_outbox",
        "user_learning_mastery",
        "agent_conversation_summaries",
        "agent_memory_items",
        "agent_preference_candidates",
        "learning_activity_events",
    }
)
AGENT_MODEL_NULLABLE_COLUMNS = frozenset({"max_tokens"})
MEMORY_OUTBOX_UNIQUE_INDEX = "uk_agent_memory_outbox_run_event"
MEMORY_OUTBOX_UNIQUE_COLUMNS = ("run_id", "event_type")
MEMORY_OUTBOX_REQUIRED_COLUMNS = frozenset({"last_error_message"})


class DatabaseSchemaError(RuntimeError):
    """Raised when the database schema cannot safely serve this application."""


def get_expected_revisions() -> frozenset[str]:
    """Return every head revision from the project's Alembic graph."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    return frozenset(scripts.get_heads())


async def verify_database_schema(
    session: AsyncSession,
    *,
    expected_revisions: Iterable[str] | None = None,
) -> frozenset[str]:
    """Fail fast when the database has not been migrated to every head."""
    expected = frozenset(expected_revisions or get_expected_revisions())

    try:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        current = frozenset(result.scalars().all())
    except Exception as exc:
        raise DatabaseSchemaError(
            "无法读取 alembic_version，数据库尚未完成 Alembic 初始化；"
            "请先在 backend 目录执行 `alembic upgrade head`。"
        ) from exc

    if current != expected:
        current_label = ", ".join(sorted(current)) or "<empty>"
        expected_label = ", ".join(sorted(expected)) or "<empty>"
        raise DatabaseSchemaError(
            "数据库结构版本与当前应用不一致："
            f"current=[{current_label}], expected=[{expected_label}]；"
            "请先在 backend 目录执行 `alembic upgrade head`。"
        )

    try:
        result = await session.execute(
            text(
                "SELECT column_name "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() "
                "AND table_name = 'agent_runs'"
            )
        )
        agent_run_columns = frozenset(result.scalars().all())
    except Exception as exc:
        raise DatabaseSchemaError(
            "无法校验 agent_runs 表结构；"
            "请先在 backend 目录执行 `alembic upgrade head`。"
        ) from exc

    missing_columns = AGENT_RUN_WORKER_COLUMNS - agent_run_columns
    if missing_columns:
        missing_label = ", ".join(sorted(missing_columns))
        raise DatabaseSchemaError(
            "数据库结构与 Alembic 版本记录不一致："
            f"agent_runs 缺少列 [{missing_label}]；"
            "请先在 backend 目录执行 `alembic upgrade head`。"
        )

    try:
        result = await session.execute(
            text(
                "SELECT table_name "
                "FROM information_schema.tables "
                "WHERE table_schema = DATABASE() "
                "AND table_name IN ("
                "'agent_model_configs', "
                "'agent_thread_memory_states', "
                "'agent_memory_events', "
                "'agent_memory_snapshots', "
        "'agent_memory_snapshot_items', "
        "'agent_memory_traces', "
        "'agent_memory_update_outbox', "
                "'user_learning_mastery', "
                "'agent_conversation_summaries', "
                "'agent_memory_items', "
                "'agent_preference_candidates', "
                "'learning_activity_events'"
                ")"
            )
        )
        agent_tables = frozenset(result.scalars().all())
    except Exception as exc:
        raise DatabaseSchemaError(
            "无法校验 Agent 必需数据表；"
            "请先在 backend 目录执行 `alembic upgrade head`。"
        ) from exc

    missing_tables = AGENT_REQUIRED_TABLES - agent_tables
    if missing_tables:
        missing_label = ", ".join(sorted(missing_tables))
        raise DatabaseSchemaError(
            "数据库结构与 Alembic 版本记录不一致："
            f"缺少 Agent 数据表 [{missing_label}]；"
            "请先在 backend 目录执行 `alembic upgrade head`。"
        )

    try:
        result = await session.execute(
            text(
                "SELECT column_name "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() "
                "AND table_name = 'agent_memory_update_outbox'"
            )
        )
        memory_outbox_columns = frozenset(result.scalars().all())
    except Exception as exc:
        raise DatabaseSchemaError(
            "无法校验 Memory Outbox 列结构；"
            "请先在 backend 目录执行 `alembic upgrade head`。"
        ) from exc

    missing_memory_outbox_columns = (
        MEMORY_OUTBOX_REQUIRED_COLUMNS - memory_outbox_columns
    )
    if missing_memory_outbox_columns:
        missing_label = ", ".join(sorted(missing_memory_outbox_columns))
        raise DatabaseSchemaError(
            "数据库结构与 Alembic 版本记录不一致："
            f"agent_memory_update_outbox 缺少列 [{missing_label}]；"
            "请先在 backend 目录执行 `alembic upgrade head`。"
        )

    try:
        result = await session.execute(
            text(
                "SELECT column_name, non_unique "
                "FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() "
                "AND table_name = 'agent_memory_update_outbox' "
                "AND index_name = 'uk_agent_memory_outbox_run_event' "
                "ORDER BY seq_in_index"
            )
        )
        memory_outbox_index_rows = [
            (str(row[0]), int(row[1])) for row in result.all()
        ]
    except Exception as exc:
        raise DatabaseSchemaError(
            "无法校验 Memory Outbox 唯一约束；"
            "请先在 backend 目录执行 `alembic upgrade head`。"
        ) from exc

    if memory_outbox_index_rows != [
        (column, 0) for column in MEMORY_OUTBOX_UNIQUE_COLUMNS
    ]:
        raise DatabaseSchemaError(
            "数据库结构与 Alembic 版本记录不一致："
            f"agent_memory_update_outbox 缺少唯一约束 [{MEMORY_OUTBOX_UNIQUE_INDEX}]；"
            "请先在 backend 目录执行 `alembic upgrade head`。"
        )

    try:
        result = await session.execute(
            text(
                "SELECT column_name, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() "
                "AND table_name = 'agent_model_configs' "
                "AND column_name IN ('max_tokens')"
            )
        )
        nullable_columns = {
            str(row[0]): str(row[1]).upper() == "YES"
            for row in result.all()
        }
    except Exception as exc:
        raise DatabaseSchemaError(
            "无法校验 agent_model_configs 列约束；"
            "请先在 backend 目录执行 `alembic upgrade head`。"
        ) from exc

    invalid_nullable_columns = {
        column
        for column in AGENT_MODEL_NULLABLE_COLUMNS
        if not nullable_columns.get(column, False)
    }
    if invalid_nullable_columns:
        invalid_label = ", ".join(sorted(invalid_nullable_columns))
        raise DatabaseSchemaError(
            "数据库结构与 Alembic 版本记录不一致："
            "agent_model_configs 以下列必须允许 NULL "
            f"[{invalid_label}]；请先在 backend 目录执行 `alembic upgrade head`。"
        )

    return current
