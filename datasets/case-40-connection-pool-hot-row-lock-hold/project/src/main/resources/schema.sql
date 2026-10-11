CREATE TABLE IF NOT EXISTS counters (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    counter_key VARCHAR(64) NOT NULL,
    value BIGINT NOT NULL,
    updated_at_ms BIGINT NOT NULL,
    UNIQUE KEY uk_counter_key (counter_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
