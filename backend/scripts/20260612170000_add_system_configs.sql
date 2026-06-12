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
        'active_parser', 'docling',
        'service_mode', 'single_active',
        'service_switch_notes', ''
    ),
    'PDF 解析器单活切换配置'
)
ON DUPLICATE KEY UPDATE
    description = VALUES(description);
