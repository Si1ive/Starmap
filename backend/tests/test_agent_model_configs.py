"""Agent 多模型配置服务测试。"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.mysql import Base
from app.modules.agent.model_configs import (
    AgentModelConfigError,
    AgentModelConfigService,
    SECRET_KEEP_MASK,
)
from app.modules.agent.models import AgentModelConfigRecord


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=[AgentModelConfigRecord.__table__],
            )
        )
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


def _payload(**overrides):
    values = {
        "display_name": "通用模型",
        "provider": "openai_compatible",
        "base_url": "https://models.example.com/v1/",
        "api_key": "secret-key",
        "model_name": "chat-model",
        "online": True,
        "selectable": True,
        "is_default": False,
        "temperature": 0.2,
        "max_tokens": 2000,
        "timeout_seconds": 60,
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_first_available_model_becomes_default_and_masks_secret(db_session):
    service = AgentModelConfigService(db_session)

    record = await service.create(_payload())
    payload = service.to_admin_dict(record)

    assert record.is_default is True
    assert record.default_slot == 1
    assert record.base_url == "https://models.example.com/v1"
    assert payload["api_key"] == SECRET_KEEP_MASK
    assert payload["has_api_key"] is True


@pytest.mark.asyncio
async def test_switching_default_clears_previous_default(db_session):
    service = AgentModelConfigService(db_session)
    first = await service.create(_payload(display_name="模型 A"))
    second = await service.create(_payload(display_name="模型 B", is_default=True))
    await db_session.refresh(first)

    assert first.is_default is False
    assert first.default_slot is None
    assert second.is_default is True
    assert second.default_slot == 1


@pytest.mark.asyncio
async def test_default_model_cannot_be_disabled_directly(db_session):
    service = AgentModelConfigService(db_session)
    record = await service.create(_payload())

    with pytest.raises(AgentModelConfigError, match="先切换默认模型"):
        await service.set_availability(
            record.id,
            online=False,
            selectable=False,
        )


@pytest.mark.asyncio
async def test_secret_mask_keeps_existing_api_key(db_session):
    service = AgentModelConfigService(db_session)
    record = await service.create(_payload())

    updated = await service.update(record.id, {"api_key": SECRET_KEEP_MASK})

    assert updated.api_key == "secret-key"


@pytest.mark.asyncio
async def test_model_config_persists_unlimited_output_tokens(db_session):
    service = AgentModelConfigService(db_session)

    record = await service.create(_payload(max_tokens=None))
    payload = service.to_admin_dict(record)

    assert record.max_tokens is None
    assert payload["max_tokens"] is None


@pytest.mark.asyncio
async def test_rejects_blank_names_after_trimming(db_session):
    service = AgentModelConfigService(db_session)

    with pytest.raises(AgentModelConfigError, match="显示名称不能为空"):
        await service.create(_payload(display_name="   "))


@pytest.mark.asyncio
async def test_public_models_only_include_online_selectable_records(db_session):
    service = AgentModelConfigService(db_session)
    default = await service.create(_payload(display_name="默认模型"))
    await service.create(
        _payload(
            display_name="未上线模型",
            online=False,
            selectable=True,
        )
    )
    await service.create(
        _payload(
            display_name="内部模型",
            online=True,
            selectable=False,
        )
    )

    records = await service.list_public()
    public_payload = [service.to_public_dict(record) for record in records]

    assert [record.id for record in records] == [default.id]
    assert public_payload == [
        {
            "id": default.id,
            "display_name": "默认模型",
            "is_default": True,
        }
    ]
    assert "api_key" not in public_payload[0]
