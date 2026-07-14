-- 监控基础设施：LLM 调用 / 服务日志 / 系统资源 / API 统计
-- 与 backend/app/models/mysql_models.py 末尾的四张表对应

CREATE TABLE IF NOT EXISTS `llm_call_logs` (
    `id` VARCHAR(32) NOT NULL,
    `provider` VARCHAR(50) NOT NULL DEFAULT 'openai_compatible' COMMENT '服务商',
    `base_url` VARCHAR(255) NULL COMMENT 'API base url',
    `model` VARCHAR(100) NOT NULL COMMENT '模型名',
    `called_by` VARCHAR(100) NULL COMMENT '调用方标识',
    `purpose` VARCHAR(100) NULL COMMENT '调用用途说明',
    `request_messages` JSON NULL COMMENT '请求 messages（截断后）',
    `request_params` JSON NULL COMMENT '请求参数',
    `response_text` TEXT NULL COMMENT '响应正文（截断）',
    `response_full` JSON NULL COMMENT '完整响应 JSON（截断）',
    `prompt_tokens` INT NOT NULL DEFAULT 0,
    `completion_tokens` INT NOT NULL DEFAULT 0,
    `total_tokens` INT NOT NULL DEFAULT 0,
    `cost_usd` DECIMAL(10,6) NOT NULL DEFAULT 0,
    `latency_ms` INT NOT NULL DEFAULT 0,
    `status` ENUM('success', 'error', 'timeout') NOT NULL DEFAULT 'success',
    `error_msg` TEXT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_llm_calls_created_at` (`created_at`),
    KEY `idx_llm_calls_status` (`status`),
    KEY `idx_llm_calls_model` (`model`),
    KEY `idx_llm_calls_called_by` (`called_by`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='LLM 调用日志';


CREATE TABLE IF NOT EXISTS `service_logs` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `level` VARCHAR(16) NOT NULL DEFAULT 'INFO',
    `logger_name` VARCHAR(120) NULL,
    `event` VARCHAR(255) NULL COMMENT '事件名/简短描述',
    `message` TEXT NULL,
    `request_id` VARCHAR(64) NULL,
    `context` JSON NULL,
    `traceback` TEXT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_service_logs_created_at` (`created_at`),
    KEY `idx_service_logs_level_time` (`level`, `created_at`),
    KEY `idx_service_logs_logger` (`logger_name`),
    KEY `idx_service_logs_request` (`request_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='后端服务日志';


CREATE TABLE IF NOT EXISTS `system_metrics` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `cpu_percent` DECIMAL(5,2) NOT NULL DEFAULT 0,
    `mem_used_mb` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `mem_total_mb` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `mem_percent` DECIMAL(5,2) NOT NULL DEFAULT 0,
    `disk_used_gb` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `disk_total_gb` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `disk_percent` DECIMAL(5,2) NOT NULL DEFAULT 0,
    `process_rss_mb` DECIMAL(10,2) NOT NULL DEFAULT 0,
    `process_cpu_percent` DECIMAL(5,2) NOT NULL DEFAULT 0,
    `sampled_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_system_metrics_sampled_at` (`sampled_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统资源采样';


CREATE TABLE IF NOT EXISTS `api_call_stats` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `endpoint` VARCHAR(255) NOT NULL,
    `method` VARCHAR(10) NOT NULL,
    `hour_bucket` DATETIME NOT NULL,
    `call_count` INT NOT NULL DEFAULT 0,
    `error_count` INT NOT NULL DEFAULT 0,
    `total_latency_ms` BIGINT NOT NULL DEFAULT 0,
    `max_latency_ms` INT NOT NULL DEFAULT 0,
    `p95_sample_ms` INT NOT NULL DEFAULT 0,
    `latency_histogram` JSON NULL COMMENT '可合并的固定桶延迟直方图',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_api_stats_bucket` (`endpoint`, `method`, `hour_bucket`),
    KEY `idx_api_stats_hour` (`hour_bucket`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='API 调用聚合统计';
