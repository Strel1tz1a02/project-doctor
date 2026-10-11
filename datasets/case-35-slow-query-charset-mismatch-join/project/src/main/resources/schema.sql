-- authors：新系统表，字符集为 utf8mb4
CREATE TABLE IF NOT EXISTS authors (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    author_code VARCHAR(40) NOT NULL,
    name VARCHAR(64) NOT NULL,
    KEY idx_authors_author_code (author_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- articles：从旧系统迁移的历史表，字符集为 utf8mb3（与 authors 不一致）
CREATE TABLE IF NOT EXISTS articles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    article_code VARCHAR(40) NOT NULL,
    title VARCHAR(200) NOT NULL,
    author_code VARCHAR(40) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_articles_author_code (author_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
