from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.operations.schema_guard import (
    DatabaseSchemaError,
    get_expected_revisions,
    verify_database_schema,
)


@pytest.mark.asyncio
async def test_schema_guard_accepts_database_at_all_alembic_heads():
    session = AsyncMock()
    revision_result = Mock()
    revision_result.scalars.return_value.all.return_value = ["head_a", "head_b"]
    columns_result = Mock()
    columns_result.scalars.return_value.all.return_value = [
        "parent_run_id",
        "root_run_id",
    ]
    session.execute.side_effect = [revision_result, columns_result]

    revisions = await verify_database_schema(
        session,
        expected_revisions={"head_a", "head_b"},
    )

    assert revisions == frozenset({"head_a", "head_b"})


@pytest.mark.asyncio
async def test_schema_guard_rejects_outdated_database():
    session = AsyncMock()
    result = Mock()
    result.scalars.return_value.all.return_value = ["old_revision"]
    session.execute.return_value = result

    with pytest.raises(DatabaseSchemaError, match="alembic upgrade head"):
        await verify_database_schema(
            session,
            expected_revisions={"current_revision"},
        )


@pytest.mark.asyncio
async def test_schema_guard_reports_missing_version_table():
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("table does not exist")

    with pytest.raises(DatabaseSchemaError, match="alembic_version"):
        await verify_database_schema(
            session,
            expected_revisions={"current_revision"},
        )


@pytest.mark.asyncio
async def test_schema_guard_rejects_missing_agent_run_worker_columns():
    session = AsyncMock()
    revision_result = Mock()
    revision_result.scalars.return_value.all.return_value = ["current_revision"]
    columns_result = Mock()
    columns_result.scalars.return_value.all.return_value = ["root_run_id"]
    session.execute.side_effect = [revision_result, columns_result]

    with pytest.raises(DatabaseSchemaError, match="parent_run_id"):
        await verify_database_schema(
            session,
            expected_revisions={"current_revision"},
        )


def test_schema_guard_reads_the_project_migration_heads():
    assert get_expected_revisions() == frozenset(
        {"20260723_repair_agent_parent"}
    )
