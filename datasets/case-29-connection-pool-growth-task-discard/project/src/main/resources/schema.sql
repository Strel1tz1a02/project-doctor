CREATE TABLE IF NOT EXISTS task_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    shard INT NOT NULL,
    status VARCHAR(16) NOT NULL,
    payload_size INT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_task_events_shard (shard)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
