-- 408 考研平台数据库初始化脚本
-- 创建学科、章节、知识点、题目等表，并插入四门学科 + 默认章节种子数据

USE starmap;

-- 学科表
CREATE TABLE IF NOT EXISTS subjects (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    name VARCHAR(50) NOT NULL COMMENT '学科名称',
    code VARCHAR(30) NOT NULL UNIQUE COMMENT '学科编码',
    description TEXT COMMENT '学科描述',
    icon VARCHAR(100) COMMENT '图标标识',
    sort_order INT DEFAULT 0 COMMENT '排序序号',
    status ENUM('active', 'inactive') DEFAULT 'active' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_subject_code (code),
    INDEX idx_subject_status (status),
    INDEX idx_subject_sort (sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='学科表';

-- 章节表
CREATE TABLE IF NOT EXISTS chapters (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    subject_id VARCHAR(32) NOT NULL COMMENT '所属学科ID',
    name VARCHAR(100) NOT NULL COMMENT '章节名称',
    description TEXT COMMENT '章节描述',
    sort_order INT DEFAULT 0 COMMENT '排序序号',
    status ENUM('active', 'inactive') DEFAULT 'active' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    INDEX idx_chapter_subject (subject_id),
    INDEX idx_chapter_sort (subject_id, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='章节表';

-- 知识点表
CREATE TABLE IF NOT EXISTS knowledge_points (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    chapter_id VARCHAR(32) NOT NULL COMMENT '所属章节ID',
    subject_id VARCHAR(32) NOT NULL COMMENT '所属学科ID（冗余）',
    title VARCHAR(200) NOT NULL COMMENT '知识点标题',
    content TEXT NOT NULL COMMENT '知识点正文（Markdown）',
    difficulty ENUM('easy', 'medium', 'hard') DEFAULT 'medium' COMMENT '难度',
    exam_frequency ENUM('high', 'medium', 'low', 'never') DEFAULT 'medium' COMMENT '考试频率',
    tags JSON COMMENT '标签列表',
    key_points JSON COMMENT '要点列表',
    related_point_ids JSON COMMENT '关联知识点ID',
    source VARCHAR(100) COMMENT '来源',
    source_page VARCHAR(20) COMMENT '来源页码',
    crawl_task_id VARCHAR(32) COMMENT '关联爬取任务ID',
    status ENUM('active', 'pending', 'deleted') DEFAULT 'pending' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    INDEX idx_kp_chapter (chapter_id),
    INDEX idx_kp_subject (subject_id),
    INDEX idx_kp_difficulty (difficulty),
    INDEX idx_kp_exam_freq (exam_frequency),
    INDEX idx_kp_status (status),
    INDEX idx_kp_title (title)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识点表';

-- 题目表
CREATE TABLE IF NOT EXISTS questions (
    id VARCHAR(32) PRIMARY KEY COMMENT '唯一标识',
    subject_id VARCHAR(32) NOT NULL COMMENT '所属学科ID',
    chapter_id VARCHAR(32) NOT NULL COMMENT '所属章节ID',
    type ENUM('choice', 'fill', 'judge', 'short_answer', 'design', 'analysis') NOT NULL COMMENT '题型',
    content TEXT NOT NULL COMMENT '题目正文',
    options JSON COMMENT '选择题选项',
    answer TEXT NOT NULL COMMENT '标准答案',
    explanation TEXT COMMENT '解析',
    difficulty ENUM('easy', 'medium', 'hard') DEFAULT 'medium' COMMENT '难度',
    source VARCHAR(100) COMMENT '来源',
    exam_year INT DEFAULT 0 COMMENT '真题年份，练习题为0',
    knowledge_point_ids JSON COMMENT '关联知识点ID',
    tags JSON COMMENT '标签',
    status ENUM('active', 'pending', 'deleted') DEFAULT 'pending' COMMENT '状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
    INDEX idx_q_subject (subject_id),
    INDEX idx_q_chapter (chapter_id),
    INDEX idx_q_type (type),
    INDEX idx_q_difficulty (difficulty),
    INDEX idx_q_exam_year (exam_year),
    INDEX idx_q_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='题目表';

-- 用户做题记录表
CREATE TABLE IF NOT EXISTS user_question_records (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(50) NOT NULL COMMENT '用户会话ID',
    question_id VARCHAR(32) NOT NULL COMMENT '题目ID',
    user_answer TEXT COMMENT '用户答案',
    is_correct BOOLEAN COMMENT '是否正确',
    time_spent INT COMMENT '用时（秒）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
    INDEX idx_uqr_session (session_id),
    INDEX idx_uqr_question (question_id),
    INDEX idx_uqr_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户做题记录表';


-- ========== 种子数据 ==========

-- 四门 408 学科
INSERT INTO subjects (id, name, code, description, icon, sort_order) VALUES
('subj_ds', '数据结构', 'data_structure', '数据结构是计算机科学的核心基础，研究数据的逻辑结构、存储结构及其运算。408考试中占比约45分。', 'ApartmentOutlined', 1),
('subj_co', '计算机组成原理', 'computer_organization', '计算机组成原理研究计算机硬件系统的基本组成和工作原理。408考试中占比约45分。', 'CloudServerOutlined', 2),
('subj_os', '操作系统', 'operating_system', '操作系统是管理计算机硬件与软件资源的系统软件。408考试中占比约35分。', 'DesktopOutlined', 3),
('subj_cn', '计算机网络', 'computer_network', '计算机网络研究计算机之间的通信协议和网络体系结构。408考试中占比约25分。', 'GlobalOutlined', 4)
ON DUPLICATE KEY UPDATE name = VALUES(name), description = VALUES(description);

-- 数据结构章节
INSERT INTO chapters (id, subject_id, name, sort_order) VALUES
('ch_ds_01', 'subj_ds', '绪论', 1),
('ch_ds_02', 'subj_ds', '线性表', 2),
('ch_ds_03', 'subj_ds', '栈、队列和数组', 3),
('ch_ds_04', 'subj_ds', '串', 4),
('ch_ds_05', 'subj_ds', '树与二叉树', 5),
('ch_ds_06', 'subj_ds', '图', 6),
('ch_ds_07', 'subj_ds', '查找', 7),
('ch_ds_08', 'subj_ds', '排序', 8)
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- 计算机组成原理章节
INSERT INTO chapters (id, subject_id, name, sort_order) VALUES
('ch_co_01', 'subj_co', '计算机系统概述', 1),
('ch_co_02', 'subj_co', '数据的表示和运算', 2),
('ch_co_03', 'subj_co', '存储器层次结构', 3),
('ch_co_04', 'subj_co', '指令系统', 4),
('ch_co_05', 'subj_co', '中央处理器', 5),
('ch_co_06', 'subj_co', '总线', 6),
('ch_co_07', 'subj_co', '输入/输出系统', 7)
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- 操作系统章节
INSERT INTO chapters (id, subject_id, name, sort_order) VALUES
('ch_os_01', 'subj_os', '操作系统概述', 1),
('ch_os_02', 'subj_os', '进程管理', 2),
('ch_os_03', 'subj_os', '内存管理', 3),
('ch_os_04', 'subj_os', '文件管理', 4),
('ch_os_05', 'subj_os', '输入/输出管理', 5)
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- 计算机网络章节
INSERT INTO chapters (id, subject_id, name, sort_order) VALUES
('ch_cn_01', 'subj_cn', '计算机网络体系结构', 1),
('ch_cn_02', 'subj_cn', '物理层', 2),
('ch_cn_03', 'subj_cn', '数据链路层', 3),
('ch_cn_04', 'subj_cn', '网络层', 4),
('ch_cn_05', 'subj_cn', '传输层', 5),
('ch_cn_06', 'subj_cn', '应用层', 6)
ON DUPLICATE KEY UPDATE name = VALUES(name);
