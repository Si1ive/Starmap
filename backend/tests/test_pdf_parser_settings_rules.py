from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.modules.operations.pdf_parser_settings import (
    build_pdf_parser_runtime_config,
    prepare_pdf_parser_update,
)
from app.modules.operations.settings_service import SystemSettingsService
from app.modules.operations.system_settings_rules import default_system_settings


def test_build_pdf_parser_runtime_config_forces_mineru():
    runtime = build_pdf_parser_runtime_config(
        {
            "active_parser": "docling",
            "service_mode": "single_active",
            "request_timeout_seconds": 120,
        }
    )

    assert runtime["active_parser"] == "mineru"
    assert runtime["service_mode"] == "mineru_only"
    assert runtime["request_timeout_seconds"] == 120


def test_prepare_pdf_parser_update_detects_unchanged_default_config():
    current = default_system_settings()["pdf_parser"]

    plan = prepare_pdf_parser_update(current, parser_name="mineru")

    assert plan.is_switching is False
    assert plan.should_audit is False
    assert plan.requires_local_health_check is False
    assert plan.next_config == current


def test_prepare_pdf_parser_update_requires_notes_for_changes():
    current = default_system_settings()["pdf_parser"]

    with pytest.raises(ValueError, match="必须填写切换备注"):
        prepare_pdf_parser_update(
            current,
            parser_name="mineru",
            request_timeout_seconds=120,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"parser_name": "docling"}, "固定为 mineru"),
        (
            {"parser_name": "mineru", "deployment_target": "embedded"},
            "仅支持 local 或 remote",
        ),
        (
            {
                "parser_name": "mineru",
                "deployment_target": "remote",
                "switch_notes": "切换到远程，回滚到本地",
            },
            "必须填写 remote_service_endpoint",
        ),
        (
            {
                "parser_name": "mineru",
                "deployment_target": "remote",
                "remote_service_endpoint": "parser.example.test",
                "switch_notes": "切换到远程，回滚到本地",
            },
            "地址格式不合法",
        ),
        (
            {
                "parser_name": "mineru",
                "request_timeout_seconds": 601,
                "switch_notes": "延长超时，回滚到原值",
            },
            "5-600",
        ),
        (
            {
                "parser_name": "mineru",
                "processing_window_size": 65,
                "switch_notes": "扩大窗口，回滚到原值",
            },
            "1-64",
        ),
    ],
)
def test_prepare_pdf_parser_update_rejects_invalid_settings(kwargs, message):
    with pytest.raises(ValueError, match=message):
        prepare_pdf_parser_update(
            default_system_settings()["pdf_parser"],
            **kwargs,
        )


def test_prepare_pdf_parser_update_builds_remote_audit_plan():
    current = default_system_settings()["pdf_parser"]

    plan = prepare_pdf_parser_update(
        current,
        parser_name=" MINERU ",
        deployment_target="REMOTE",
        remote_service_endpoint=" https://parser.example.test ",
        request_timeout_seconds=180,
        processing_window_size=4,
        switch_notes=" 迁移到远程服务，异常时回滚本地 ",
    )

    assert plan.is_switching is True
    assert plan.should_audit is True
    assert plan.requires_local_health_check is False
    assert plan.next_config["active_parser"] == "mineru"
    assert plan.next_config["deployment_target"] == "remote"
    assert plan.next_config["remote_service_endpoint"] == (
        "https://parser.example.test"
    )
    assert plan.new_audit_values["switch_notes"] == (
        "迁移到远程服务，异常时回滚本地"
    )


@pytest.mark.asyncio
async def test_update_pdf_parser_executes_local_health_check_and_audit():
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    service = SystemSettingsService(db)
    current = default_system_settings()
    service.load = AsyncMock(return_value=current)
    service.save = AsyncMock(side_effect=lambda data: data)

    with patch(
        "app.modules.operations.settings_service.inspect_parser_health",
        return_value={"health_status": "ready"},
    ) as inspect_health:
        saved = await service.update_pdf_parser(
            "mineru",
            local_service_endpoint="http://localhost:8091",
            switch_notes="切换本地端口，回滚到 8090",
            user_id="admin-1",
        )

    inspect_health.assert_called_once()
    assert saved["pdf_parser"]["local_service_endpoint"] == (
        "http://localhost:8091"
    )
    audit = db.add.call_args.args[0]
    assert audit.action == "pdf_parser_switch"
    assert audit.new_values["active_parser"] == "mineru"
    db.flush.assert_awaited_once()
