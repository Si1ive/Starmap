from app.modules.operations.system_settings_rules import (
    default_config_description,
    default_system_settings,
    merge_section_dicts,
    merge_settings_defaults,
    sanitize_settings_input,
)


def test_default_system_settings_returns_independent_mineru_config():
    first = default_system_settings()
    second = default_system_settings()

    first["llm"]["model"] = "changed"

    assert second["llm"]["model"] != "changed"
    assert second["pdf_parser"]["active_parser"] == "mineru"
    assert second["pdf_parser"]["service_mode"] == "mineru_only"


def test_merge_settings_defaults_preserves_custom_sections_and_forces_mineru():
    source = {
        "llm": {"enabled": True},
        "pdf_parser": {
            "active_parser": "docling",
            "service_mode": "single_active",
        },
        "custom": {"enabled": True},
    }

    merged = merge_settings_defaults(source)

    assert merged["llm"]["enabled"] is True
    assert merged["llm"]["provider"] == "openai_compatible"
    assert merged["custom"] == {"enabled": True}
    assert merged["pdf_parser"]["active_parser"] == "mineru"
    assert merged["pdf_parser"]["service_mode"] == "mineru_only"
    assert source["pdf_parser"]["active_parser"] == "docling"


def test_merge_settings_defaults_preserves_unlimited_llm_tokens():
    merged = merge_settings_defaults(
        {
            "outline_llm": {"max_tokens": None},
            "doc_meta_llm": {"max_tokens": None},
        }
    )

    assert merged["outline_llm"]["max_tokens"] is None
    assert merged["doc_meta_llm"]["max_tokens"] is None


def test_merge_section_dicts_recursively_merges_without_mutating_inputs():
    base = {"llm": {"enabled": False, "model": "base"}}
    updates = {"llm": {"enabled": True}}

    merged = merge_section_dicts(base, updates)

    assert merged == {"llm": {"enabled": True, "model": "base"}}
    assert base["llm"]["enabled"] is False


def test_sanitize_settings_input_filters_scalars_and_normalizes_pdf_parser():
    source = {
        "llm": {"enabled": True},
        "ignored": "value",
        "pdf_parser": {
            "active_parser": "docling",
            "service_mode": "single_active",
            "request_timeout_seconds": 120,
        },
    }

    sanitized = sanitize_settings_input(source)

    assert "ignored" not in sanitized
    assert sanitized["llm"] == {"enabled": True}
    assert sanitized["pdf_parser"]["active_parser"] == "mineru"
    assert sanitized["pdf_parser"]["service_mode"] == "mineru_only"
    assert sanitized["pdf_parser"]["request_timeout_seconds"] == 120


def test_default_config_description_handles_known_and_unknown_sections():
    assert default_config_description("crawler") == "Scrapy 爬虫运行配置"
    assert default_config_description("unknown") == "系统配置"
