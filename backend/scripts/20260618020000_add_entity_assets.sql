-- 实体（知识点/题目）与文档资产的多对多关联
-- 注意：必须显式指定 COLLATE=utf8mb4_unicode_ci，与库默认 collation 一致
-- 否则 MySQL 8.0 会用 utf8mb4_0900_ai_ci，与 document_assets.id 的 collation 冲突，导致外键不兼容

CREATE TABLE IF NOT EXISTS `entity_asset_links` (
    `id` VARCHAR(32) NOT NULL,
    `entity_type` ENUM('knowledge_point', 'question') NOT NULL,
    `entity_id` VARCHAR(32) NOT NULL,
    `asset_id` VARCHAR(32) NOT NULL,
    `relation` ENUM('inline', 'reference', 'related') NOT NULL DEFAULT 'inline',
    `sort_order` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_entity_asset` (`entity_type`, `entity_id`, `asset_id`),
    KEY `idx_entity_asset_entity` (`entity_type`, `entity_id`),
    KEY `idx_entity_asset_asset` (`asset_id`),
    CONSTRAINT `fk_entity_asset_asset` FOREIGN KEY (`asset_id`)
        REFERENCES `document_assets` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='实体-资产关联';

-- 让 document_assets.file_path 允许为空（公式/HTML 表格存 metadata_json 即可）
ALTER TABLE `document_assets`
    MODIFY COLUMN `file_path` VARCHAR(500) NULL COMMENT '资产文件路径（图片有，公式/表格无）';
