CREATE TABLE IF NOT EXISTS export_rows (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    segment VARCHAR(32) NOT NULL,
    amount BIGINT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_export_segment_id (segment, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
