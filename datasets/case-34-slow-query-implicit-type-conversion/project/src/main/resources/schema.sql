CREATE TABLE IF NOT EXISTS members (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    member_no VARCHAR(32) NOT NULL,
    nickname VARCHAR(64) NOT NULL,
    level VARCHAR(16) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_members_member_no (member_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
