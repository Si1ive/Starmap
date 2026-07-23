"""Validate that the connected database matches the Alembic migration graph."""

from pathlib import Path
from typing import Iterable

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


BACKEND_DIR = Path(__file__).resolve().parents[3]
AGENT_RUN_WORKER_COLUMNS = frozenset({"parent_run_id", "root_run_id"})


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

    return current
