"""Validate that the connected database matches the Alembic migration graph."""

from pathlib import Path
from typing import Iterable

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


BACKEND_DIR = Path(__file__).resolve().parents[3]


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

    return current
