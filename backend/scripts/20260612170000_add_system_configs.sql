USE starmap;

CREATE TABLE IF NOT EXISTS system_configs (
    config_key VARCHAR(100) PRIMARY KEY COMMENT '配置键',
    config_value JSON COMMENT '配置值 JSON',
    description VARCHAR(255) COMMENT '配置说明',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统配置表';

INSERT INTO system_configs (config_key, config_value, description)
VALUES (
    'pdf_parser',
    JSON_OBJECT(
        'active_parser', 'mineru',
        'service_mode', 'single_active',
        'service_switch_notes', ''
    ),
    'PDF 解析器单活切换配置'
)
ON DUPLICATE KEY UPDATE
    description = VALUES(description);

INSERT INTO system_configs (config_key, config_value, description)
VALUES (
    'pdf_structure_llm',
    JSON_OBJECT(
        'enabled', false,
        'provider', 'openai_compatible',
        'base_url', '',
        'api_key', '',
        'model', 'gpt-4',
        'temperature', 0.1,
        'max_tokens', 2000,
        'timeout_seconds', 60,
        'system_prompt', '你是一个PDF题目结构分析专家，负责判断跨页、跨列导致的题目拆分和选项缺失问题。'
    ),
    'PDF 文档结构解析 LLM 配置'
)
ON DUPLICATE KEY UPDATE
    description = VALUES(description);
