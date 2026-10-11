CREATE TABLE IF NOT EXISTS telemetry_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    model VARCHAR(32) NOT NULL,
    tokens BIGINT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_telemetry_model (model)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
