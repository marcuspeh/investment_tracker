-- 01_initial_setup.sql
-- Creates the four core tables produced by Tortoise.generate_schemas()
-- on first startup. Apply this against a fresh database if you prefer
-- to bootstrap the schema manually; otherwise let Tortoise create the
-- tables on first run.

CREATE TABLE users (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    telegram_chat_id BIGINT NOT NULL,
    name VARCHAR(255) NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                 ON UPDATE CURRENT_TIMESTAMP(6),
    deleted_at DATETIME(6) NULL,
    UNIQUE KEY uniq_users_telegram_chat_id (telegram_chat_id)
);

CREATE TABLE user_emails (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    email VARCHAR(320) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                 ON UPDATE CURRENT_TIMESTAMP(6),
    deleted_at DATETIME(6) NULL,
    UNIQUE KEY uniq_user_emails_email (email)
);

CREATE TABLE imported_emails (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    message_id VARCHAR(191) NOT NULL,
    status VARCHAR(16) NOT NULL,
    reason VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uniq_imported_emails_message_id (message_id)
);

CREATE TABLE trades (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    side VARCHAR(8) NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    quantity DECIMAL(18, 6) NOT NULL,
    price DECIMAL(18, 6) NOT NULL,
    currency VARCHAR(8) NOT NULL DEFAULT 'USD',
    account_id VARCHAR(64) NOT NULL,
    notional DECIMAL(18, 2) NULL,
    description TEXT NULL,
    trade_time DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                 ON UPDATE CURRENT_TIMESTAMP(6),
    deleted_at DATETIME(6) NULL,
    KEY idx_trades_user_time (user_id, trade_time),
    KEY idx_trades_user_deleted (user_id, deleted_at),
    KEY idx_trades_symbol (symbol)
);
