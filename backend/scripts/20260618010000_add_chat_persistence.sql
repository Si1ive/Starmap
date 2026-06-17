-- 对话会话与消息持久化（chat_sessions / chat_messages）

CREATE TABLE IF NOT EXISTS `chat_sessions` (
    `id` VARCHAR(64) NOT NULL COMMENT 'session_id',
    `user_id` VARCHAR(64) NULL,
    `title` VARCHAR(255) NULL,
    `first_message` TEXT NULL,
    `last_message` TEXT NULL,
    `message_count` INT NOT NULL DEFAULT 0,
    `has_knowledge` TINYINT(1) NOT NULL DEFAULT 0,
    `metadata_json` JSON NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_chat_sessions_user` (`user_id`),
    KEY `idx_chat_sessions_updated` (`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话会话';


CREATE TABLE IF NOT EXISTS `chat_messages` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `session_id` VARCHAR(64) NOT NULL,
    `role` ENUM('user', 'assistant', 'system') NOT NULL,
    `content` TEXT NOT NULL,
    `citations` JSON NULL,
    `llm_call_id` VARCHAR(32) NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_chat_messages_session` (`session_id`, `created_at`),
    CONSTRAINT `fk_chat_messages_session` FOREIGN KEY (`session_id`)
        REFERENCES `chat_sessions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话消息';
