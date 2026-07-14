"""Crawler runtime settings rule tests."""

import pytest

from app.modules.operations.crawler_settings import (
    default_crawler_settings,
    normalize_crawler_settings,
    redact_crawler_runtime_config,
)


def test_default_crawler_settings_returns_independent_values():
    first = default_crawler_settings()
    second = default_crawler_settings()

    first["concurrent_requests"] = 12

    assert second["concurrent_requests"] == 4


def test_normalize_crawler_settings_can_ignore_unknown_stored_fields():
    normalized = normalize_crawler_settings(
        {
            "concurrent_requests": 8,
            "legacy_field": "ignored",
        },
        reject_unknown=False,
    )

    assert normalized["concurrent_requests"] == 8
    assert "legacy_field" not in normalized


@pytest.mark.parametrize(
    "value",
    [True, 1.5, 0, 65],
)
def test_normalize_crawler_settings_rejects_invalid_concurrency(value):
    with pytest.raises(ValueError):
        normalize_crawler_settings(
            {"concurrent_requests": value}
        )


def test_redact_crawler_runtime_config_does_not_mutate_input():
    config = {
        **default_crawler_settings(),
        "proxy_enabled": True,
        "proxy_url": "http://user:secret@127.0.0.1:7890",
    }

    redacted = redact_crawler_runtime_config(config)

    assert redacted["proxy_url"] == "[configured]"
    assert config["proxy_url"] == "http://user:secret@127.0.0.1:7890"
