-- 爬虫管理增强模块数据库迁移 v2.0
-- 版本：v2.0
-- 日期：2026-06-05
-- 说明：新增爬取源管理、统计报表、定时任务相关表

-- ============================================
-- 1. 新增爬取源配置表
-- ============================================
CREATE TABLE IF NOT EXISTS crawl_sources (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    name VARCHAR(100) NOT NULL COMMENT '源名称（如：维基百科中文）',
    code VARCHAR(50) NOT NULL UNIQUE COMMENT '源编码（如：wikipedia_zh）',
    type VARCHAR(50) COMMENT '源类型：encyclopedia/social/official/news',
    base_url VARCHAR(500) COMMENT '基础URL',
    config JSON COMMENT '源配置：选择器、字段映射等',
    request_interval DECIMAL(3,1) DEFAULT 1.0 COMMENT '请求间隔(秒)',
    daily_limit INT DEFAULT 1000 COMMENT '每日请求上限',
    concurrent_limit INT DEFAULT 5 COMMENT '并发数限制',
    status ENUM('active', 'inactive', 'error', 'deprecated') DEFAULT 'active',
    health_status ENUM('healthy', 'degraded', 'down') DEFAULT 'healthy',
    last_health_check DATETIME COMMENT '最后健康检查时间',
    total_requests BIGINT DEFAULT 0 COMMENT '累计请求数',
    total_success BIGINT DEFAULT 0 COMMENT '累计成功数',
    total_failed BIGINT DEFAULT 0 COMMENT '累计失败数',
    avg_response_time DECIMAL(8,2) COMMENT '平均响应时间(ms)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_type (type),
    INDEX idx_health (health_status)
) COMMENT='爬取源配置表';

-- ============================================
-- 2. 新增爬取源统计表（按天汇总）
-- ============================================
CREATE TABLE IF NOT EXISTS crawl_source_stats (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_id VARCHAR(32) NOT NULL COMMENT '爬取源ID',
    stat_date DATE NOT NULL COMMENT '统计日期',
    total_requests INT DEFAULT 0 COMMENT '总请求数',
    success_requests INT DEFAULT 0 COMMENT '成功请求数',
    failed_requests INT DEFAULT 0 COMMENT '失败请求数',
    timeout_requests INT DEFAULT 0 COMMENT '超时请求数',
    rate_limited_requests INT DEFAULT 0 COMMENT '被限流请求数',
    persons_extracted INT DEFAULT 0 COMMENT '提取人物数',
    works_extracted INT DEFAULT 0 COMMENT '提取作品数',
    relations_extracted INT DEFAULT 0 COMMENT '提取关系数',
    valid_records INT DEFAULT 0 COMMENT '有效记录数',
    duplicate_records INT DEFAULT 0 COMMENT '重复记录数',
    avg_response_time DECIMAL(8,2) COMMENT '平均响应时间(ms)',
    min_response_time DECIMAL(8,2) COMMENT '最小响应时间(ms)',
    max_response_time DECIMAL(8,2) COMMENT '最大响应时间(ms)',
    p95_response_time DECIMAL(8,2) COMMENT 'P95响应时间(ms)',
    avg_completeness DECIMAL(5,2) COMMENT '平均字段完整度(%)',
    total_duration INT DEFAULT 0 COMMENT '总耗时(秒)',
    data_size_mb DECIMAL(8,2) COMMENT '数据大小(MB)',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_source_date (source_id, stat_date),
    INDEX idx_stat_date (stat_date),
    INDEX idx_source_id (source_id)
) COMMENT='爬取源日统计表';

-- ============================================
-- 3. 新增定时任务配置表
-- ============================================
CREATE TABLE IF NOT EXISTS crawl_schedules (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    name VARCHAR(200) NOT NULL COMMENT '任务名称',
    description TEXT COMMENT '任务描述',
    task_type ENUM('full', 'incremental', 'targeted', 'health_check', 'cleanup') NOT NULL,
    source_ids JSON COMMENT '关联的爬取源ID列表',
    target_config JSON COMMENT '目标配置',
    cron_expression VARCHAR(100) NOT NULL COMMENT 'Cron表达式',
    timezone VARCHAR(50) DEFAULT 'Asia/Shanghai' COMMENT '时区',
    is_enabled BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    max_retries INT DEFAULT 3 COMMENT '失败重试次数',
    retry_interval INT DEFAULT 300 COMMENT '重试间隔(秒)',
    concurrent_limit INT DEFAULT 1 COMMENT '并发数限制',
    timeout INT DEFAULT 3600 COMMENT '任务超时(秒)',
    notify_on_success BOOLEAN DEFAULT FALSE COMMENT '成功时通知',
    notify_on_failure BOOLEAN DEFAULT TRUE COMMENT '失败时通知',
    notify_emails JSON COMMENT '通知邮箱列表',
    total_runs INT DEFAULT 0 COMMENT '总执行次数',
    success_runs INT DEFAULT 0 COMMENT '成功次数',
    failed_runs INT DEFAULT 0 COMMENT '失败次数',
    last_run_at DATETIME COMMENT '最后执行时间',
    last_run_status ENUM('success', 'failed', 'running', 'timeout') COMMENT '最后执行状态',
    last_run_duration INT COMMENT '最后执行耗时(秒)',
    next_run_at DATETIME COMMENT '下次执行时间',
    created_by VARCHAR(32) COMMENT '创建者',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_enabled (is_enabled),
    INDEX idx_next_run (next_run_at),
    INDEX idx_task_type (task_type)
) COMMENT='定时任务配置表';

-- ============================================
-- 4. 新增定时任务执行历史表
-- ============================================
CREATE TABLE IF NOT EXISTS crawl_schedule_runs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    schedule_id VARCHAR(32) NOT NULL COMMENT '定时任务ID',
    task_id VARCHAR(32) COMMENT '关联的爬取任务ID',
    status ENUM('running', 'success', 'failed', 'timeout', 'cancelled') NOT NULL,
    started_at DATETIME NOT NULL COMMENT '开始时间',
    completed_at DATETIME COMMENT '完成时间',
    duration INT COMMENT '执行耗时(秒)',
    total_requests INT DEFAULT 0,
    success_count INT DEFAULT 0,
    failed_count INT DEFAULT 0,
    error_message TEXT COMMENT '错误信息',
    log_summary TEXT COMMENT '日志摘要',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_schedule_id (schedule_id),
    INDEX idx_status (status),
    INDEX idx_started_at (started_at)
) COMMENT='定时任务执行历史表';

-- ============================================
-- 5. 修改现有表
-- ============================================

-- 5.1 修改 crawl_tasks 表，增加 source_id 字段
ALTER TABLE crawl_tasks 
    ADD COLUMN IF NOT EXISTS source_id VARCHAR(32) COMMENT '爬取源ID',
    ADD COLUMN IF NOT EXISTS total_requests INT DEFAULT 0 COMMENT '总请求数',
    ADD COLUMN IF NOT EXISTS error_message TEXT COMMENT '错误信息',
    ADD INDEX IF NOT EXISTS idx_ct_source_id (source_id);

ALTER TABLE crawl_tasks
    MODIFY COLUMN task_type ENUM('full', 'incremental', 'targeted', 'health_check', 'cleanup') COMMENT '任务类型';

-- 5.2 修改 crawl_logs 表，增加 source_id 和 details 字段
ALTER TABLE crawl_logs 
    ADD COLUMN IF NOT EXISTS source_id VARCHAR(32) COMMENT '爬取源ID',
    ADD COLUMN IF NOT EXISTS stage VARCHAR(50) COMMENT '阶段: fetch/parse/validate/store',
    ADD COLUMN IF NOT EXISTS details JSON COMMENT '详细日志信息',
    ADD INDEX IF NOT EXISTS idx_cl_source_id (source_id);

-- 修改 crawl_logs 的 level 枚举，增加 SUCCESS 和 CRITICAL
-- 注意：MySQL 8.0 支持 ALTER COLUMN 修改 ENUM，但需要重新指定所有值
-- 这里使用 MODIFY COLUMN
ALTER TABLE crawl_logs 
    MODIFY COLUMN level ENUM('INFO', 'WARNING', 'ERROR', 'DEBUG', 'SUCCESS', 'CRITICAL') DEFAULT 'INFO';

-- ============================================
-- 6. 初始化默认爬取源
-- ============================================
INSERT INTO crawl_sources (id, name, code, type, base_url, config, status) VALUES
('src_001', '维基百科（中文）', 'wikipedia_zh', 'encyclopedia', 'https://zh.wikipedia.org/wiki/', 
 '{"selectors": {"title": "h1.firstHeading", "summary": "div.mw-parser-output > p:first-of-type"}, "anti_detection": {"user_agent_rotation": true, "delay_range": [1.0, 3.0]}}', 
 'active'),
('src_002', '豆瓣电影', 'douban_movie', 'social', 'https://movie.douban.com/',
 '{"selectors": {"title": "span[property=\\"v:itemreviewed\\"]", "rating": "strong[property=\\"v:average\\"]"}, "anti_detection": {"user_agent_rotation": true, "delay_range": [2.0, 5.0]}}',
 'active')
ON DUPLICATE KEY UPDATE 
    name = VALUES(name),
    type = VALUES(type),
    base_url = VALUES(base_url),
    config = VALUES(config);

-- ============================================
-- 7. 创建统计视图（方便查询）
-- ============================================
CREATE OR REPLACE VIEW v_crawl_source_overview AS
SELECT 
    s.id,
    s.name,
    s.code,
    s.type,
    s.status,
    s.health_status,
    s.total_requests,
    s.total_success,
    s.total_failed,
    ROUND(s.total_success / NULLIF(s.total_requests, 0) * 100, 2) AS success_rate,
    s.avg_response_time,
    s.last_health_check,
    COALESCE(st.today_requests, 0) AS today_requests,
    COALESCE(st.today_success, 0) AS today_success
FROM crawl_sources s
LEFT JOIN (
    SELECT 
        source_id,
        SUM(total_requests) AS today_requests,
        SUM(success_requests) AS today_success
    FROM crawl_source_stats
    WHERE stat_date = CURDATE()
    GROUP BY source_id
) st ON s.id = st.source_id;

-- ============================================
-- 验证：检查所有表是否创建成功
-- ============================================
SELECT 
    TABLE_NAME,
    TABLE_COMMENT
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = DATABASE()
AND TABLE_NAME IN ('crawl_sources', 'crawl_source_stats', 'crawl_schedules', 'crawl_schedule_runs')
ORDER BY TABLE_NAME;
