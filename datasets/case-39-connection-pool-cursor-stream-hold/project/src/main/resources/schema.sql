CREATE TABLE IF NOT EXISTS report_rows (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    region VARCHAR(32) NOT NULL,
    metric VARCHAR(32) NOT NULL,
    amount BIGINT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_report_region_id (region, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
