-- StarMap MySQL 数据库初始化脚本
-- 在 Docker 容器首次启动时自动执行

-- 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS starmap 
    CHARACTER SET utf8mb4 
    COLLATE utf8mb4_unicode_ci;

USE starmap;

-- 人物表
CREATE TABLE IF NOT EXISTS persons (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识，如 person_001',
    name VARCHAR(100) NOT NULL COMMENT '中文名',
    name_en VARCHAR(100) COMMENT '英文名',
    avatar VARCHAR(500) COMMENT '头像URL',
    gender ENUM('male', 'female', 'unknown') COMMENT '性别',
    birth_date DATE COMMENT '出生日期',
    birth_place VARCHAR(200) COMMENT '出生地',
    nationality VARCHAR(50) COMMENT '国籍',
    height DECIMAL(5,2) COMMENT '身高(cm)',
    summary TEXT COMMENT '简介',
    biography LONGTEXT COMMENT '详细传记',
    popularity_score DECIMAL(5,2) COMMENT '知名度评分 0-100',
    categories JSON COMMENT '分类标签，如 ["singer", "actor"]',
    
    -- 数据状态
    status ENUM('active', 'pending', 'deleted') DEFAULT 'pending' COMMENT '数据状态',
    data_quality_score DECIMAL(3,2) COMMENT '数据质量评分',
    
    -- 爬取信息
    crawl_source VARCHAR(50) COMMENT '数据来源：wikipedia, douban',
    crawl_url VARCHAR(500) COMMENT '原始爬取URL',
    crawl_task_id VARCHAR(32) COMMENT '关联的爬取任务ID',
    raw_data JSON COMMENT '保留原始爬取数据（清洗前）',
    
    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- 索引
    INDEX idx_name (name),
    INDEX idx_name_en (name_en),
    INDEX idx_nationality (nationality),
    INDEX idx_status (status),
    INDEX idx_birth_date (birth_date),
    INDEX idx_crawl_source (crawl_source),
    INDEX idx_created_at (created_at),
    FULLTEXT INDEX ft_summary (summary, biography)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='人物表';

-- 作品表
CREATE TABLE IF NOT EXISTS works (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    title VARCHAR(200) NOT NULL COMMENT '标题',
    title_en VARCHAR(200) COMMENT '英文标题',
    type ENUM('album', 'movie', 'tv', 'drama', 'book', 'single', 'ep') COMMENT '类型',
    release_date DATE COMMENT '发布日期',
    genre VARCHAR(100) COMMENT '流派/类型',
    rating DECIMAL(3,1) COMMENT '评分 0-10',
    poster VARCHAR(500) COMMENT '海报URL',
    summary TEXT COMMENT '简介',
    
    -- 数据状态
    status ENUM('active', 'pending', 'deleted') DEFAULT 'pending',
    
    -- 爬取信息
    crawl_source VARCHAR(50),
    crawl_url VARCHAR(500),
    crawl_task_id VARCHAR(32),
    raw_data JSON,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_title (title),
    INDEX idx_type (type),
    INDEX idx_release_date (release_date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='作品表';

-- 人物-作品关联表
CREATE TABLE IF NOT EXISTS person_works (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    person_id VARCHAR(32) NOT NULL COMMENT '人物ID',
    work_id VARCHAR(32) NOT NULL COMMENT '作品ID',
    role VARCHAR(100) COMMENT '饰演角色/职位',
    role_type ENUM('actor', 'director', 'singer', 'composer', 'producer', 'writer') COMMENT '角色类型',
    is_lead BOOLEAN DEFAULT FALSE COMMENT '是否主演/主唱',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE CASCADE,
    FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE,
    UNIQUE KEY uk_person_work_role (person_id, work_id, role_type),
    INDEX idx_person_id (person_id),
    INDEX idx_work_id (work_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='人物作品关联表';

-- 人物关系表
CREATE TABLE IF NOT EXISTS person_relations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source_id VARCHAR(32) NOT NULL COMMENT '源人物ID',
    target_id VARCHAR(32) NOT NULL COMMENT '目标人物ID',
    relation_type ENUM('MARRIED_TO', 'COLLABORATED_WITH', 'MENTOR_OF', 'RELATIVE', 'FRIEND') 
        COMMENT '关系类型',
    properties JSON COMMENT '关系属性，如 {start_date, end_date, status, work_id}',
    confidence DECIMAL(3,2) DEFAULT 1.0 COMMENT '关系可信度 0-1',
    source VARCHAR(50) COMMENT '数据来源：wikipedia, manual, inferred',
    
    -- 验证状态
    is_verified BOOLEAN DEFAULT FALSE COMMENT '是否人工验证',
    verified_by VARCHAR(32) COMMENT '验证人',
    verified_at TIMESTAMP NULL COMMENT '验证时间',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (source_id) REFERENCES persons(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES persons(id) ON DELETE CASCADE,
    UNIQUE KEY uk_relation (source_id, target_id, relation_type),
    INDEX idx_source_id (source_id),
    INDEX idx_target_id (target_id),
    INDEX idx_relation_type (relation_type),
    INDEX idx_confidence (confidence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='人物关系表';

-- 爬虫任务表
CREATE TABLE IF NOT EXISTS crawl_tasks (
    id VARCHAR(32) PRIMARY KEY COMMENT '任务ID',
    name VARCHAR(200) COMMENT '任务名称',
    task_type ENUM('full', 'incremental', 'targeted') COMMENT '任务类型',
    source VARCHAR(50) COMMENT '数据源：wikipedia, douban',
    target_count INT COMMENT '计划爬取数量',
    completed_count INT DEFAULT 0 COMMENT '已完成数量',
    success_count INT DEFAULT 0 COMMENT '成功数量',
    failed_count INT DEFAULT 0 COMMENT '失败数量',
    status ENUM('pending', 'running', 'completed', 'failed', 'stopped') DEFAULT 'pending',
    progress DECIMAL(5,2) DEFAULT 0 COMMENT '进度 0-100',
    config JSON COMMENT '任务配置',
    
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_by VARCHAR(32) COMMENT '创建人',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_status (status),
    INDEX idx_task_type (task_type),
    INDEX idx_source (source),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='爬虫任务表';

-- 爬虫日志表
CREATE TABLE IF NOT EXISTS crawl_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(32) NOT NULL COMMENT '任务ID',
    level ENUM('INFO', 'WARNING', 'ERROR', 'DEBUG') DEFAULT 'INFO',
    
    resource_url VARCHAR(500) COMMENT '爬取URL',
    resource_name VARCHAR(200) COMMENT '资源名称',
    resource_type ENUM('person', 'work', 'page') COMMENT '资源类型',
    
    action VARCHAR(50) COMMENT '操作：download, parse, store, skip',
    status ENUM('success', 'failed', 'retry', 'pending') COMMENT '状态',
    duration_ms INT COMMENT '耗时(ms)',
    
    message TEXT COMMENT '日志消息',
    error_type VARCHAR(50) COMMENT '错误类型：timeout, 404, anti_crawl, parse_error',
    error_detail TEXT COMMENT '错误详情',
    retry_count INT DEFAULT 0 COMMENT '重试次数',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_task_id (task_id),
    INDEX idx_level (level),
    INDEX idx_status (status),
    INDEX idx_resource_type (resource_type),
    INDEX idx_error_type (error_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='爬虫日志表';

-- 管理员用户表
CREATE TABLE IF NOT EXISTS admin_users (
    id VARCHAR(32) PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('super_admin', 'data_admin', 'operator') DEFAULT 'operator',
    permissions JSON COMMENT '权限列表',
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMP NULL,
    last_login_ip VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_username (username),
    INDEX idx_role (role),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='管理员用户表';

-- 审计日志表
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(32) COMMENT '操作用户',
    action VARCHAR(100) COMMENT '操作：CREATE/UPDATE/DELETE/LOGIN',
    resource_type VARCHAR(50) COMMENT '资源类型：person/work/relation',
    resource_id VARCHAR(32) COMMENT '资源ID',
    old_values JSON COMMENT '修改前的值',
    new_values JSON COMMENT '修改后的值',
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_user_id (user_id),
    INDEX idx_resource (resource_type, resource_id),
    INDEX idx_action (action),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审计日志表';

-- 插入默认管理员账号（密码需要在应用层哈希后更新）
-- 默认密码: admin123，请在首次登录后修改
INSERT IGNORE INTO admin_users (id, username, email, password_hash, role, permissions) VALUES 
('admin_001', 'admin', 'admin@starmap.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiAYMyzJ/I1K', 'super_admin', '["*"]');

-- 创建统计视图
CREATE OR REPLACE VIEW v_crawl_summary AS
SELECT 
    status,
    COUNT(*) as task_count,
    SUM(target_count) as total_target,
    SUM(completed_count) as total_completed,
    SUM(success_count) as total_success,
    SUM(failed_count) as total_failed,
    AVG(progress) as avg_progress
FROM crawl_tasks
GROUP BY status;

CREATE OR REPLACE VIEW v_person_summary AS
SELECT 
    status,
    COUNT(*) as person_count,
    COUNT(DISTINCT nationality) as nationality_count,
    AVG(popularity_score) as avg_popularity
FROM persons
GROUP BY status;
