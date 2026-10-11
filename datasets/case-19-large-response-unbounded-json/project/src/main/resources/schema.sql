CREATE TABLE IF NOT EXISTS provider_releases (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    provider VARCHAR(64) NOT NULL,
    release_tag VARCHAR(128) NOT NULL,
    payload LONGTEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_provider_releases_provider (provider)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
