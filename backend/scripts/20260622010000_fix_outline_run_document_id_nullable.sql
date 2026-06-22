-- 修复 outline_ingestion_runs.document_id 为可 NULL
-- 原因：import_from_llm_result 创建 run 时没有 document_id（入库阶段不依赖文档）
-- 需要先删除外键约束，修改列，再重新添加外键（用 SET NULL 替代 CASCADE）

ALTER TABLE `outline_ingestion_runs`
    DROP FOREIGN KEY `outline_ingestion_runs_ibfk_1`;

ALTER TABLE `outline_ingestion_runs`
    MODIFY COLUMN `document_id` VARCHAR(32) NULL COMMENT '源文档ID（拆分阶段有，入库阶段可能无）';

ALTER TABLE `outline_ingestion_runs`
    ADD CONSTRAINT `outline_ingestion_runs_ibfk_1` FOREIGN KEY (`document_id`)
        REFERENCES `documents` (`id`) ON DELETE SET NULL;
