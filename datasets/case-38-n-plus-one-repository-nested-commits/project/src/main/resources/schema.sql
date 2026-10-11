CREATE TABLE IF NOT EXISTS committers (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS repositories (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    owner VARCHAR(64) NOT NULL,
    name VARCHAR(140) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_repositories_created_at (created_at_ms)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS commits (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    repository_id BIGINT NOT NULL,
    committer_id BIGINT NOT NULL,
    message VARCHAR(200) NOT NULL,
    KEY idx_commits_repository_id (repository_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
