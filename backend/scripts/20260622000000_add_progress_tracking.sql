-- 为 parse_runs 和 outline_ingestion_runs 添加进度跟踪字段
-- 用于实时展示解析 / 入库任务的详细进度

-- 扩展 parse_runs：增加阶段和逐页进度字段
ALTER TABLE `parse_runs`
    ADD COLUMN `current_stage` VARCHAR(50) NULL COMMENT '当前阶段：parsing/completed' AFTER `status`,
    ADD COLUMN `current_page` INT NULL COMMENT '当前处理页码' AFTER `current_stage`,
    ADD COLUMN `total_pages` INT NULL COMMENT '总页数（预估或实际）' AFTER `current_page`,
    ADD COLUMN `stage_detail` VARCHAR(500) NULL COMMENT '阶段详情文本（如"正在解析第 15/120 页"）' AFTER `total_pages`;

-- 扩展 outline_ingestion_runs：增加阶段字段（已有 current_subject_name 和 processed_subjects）
ALTER TABLE `outline_ingestion_runs`
    ADD COLUMN `current_stage` VARCHAR(50) NULL COMMENT '当前阶段：parsing/splitting/importing/completed' AFTER `status`,
    ADD COLUMN `stage_detail` VARCHAR(500) NULL COMMENT '阶段详情文本' AFTER `current_stage`;

-- document_id 改为可 NULL（入库阶段不依赖文档，用 SET NULL 替代 CASCADE）
ALTER TABLE `outline_ingestion_runs`
    MODIFY COLUMN `document_id` VARCHAR(32) NULL COMMENT '源文档ID（拆分阶段有，入库阶段可能无）',
    DROP FOREIGN KEY `outline_ingestion_runs_ibfk_1`,
    ADD CONSTRAINT `outline_ingestion_runs_ibfk_1` FOREIGN KEY (`document_id`)
        REFERENCES `documents` (`id`) ON DELETE SET NULL;
