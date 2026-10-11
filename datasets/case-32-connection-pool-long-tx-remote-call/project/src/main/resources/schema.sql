CREATE TABLE IF NOT EXISTS reconcile_tasks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_no VARCHAR(32) NOT NULL,
    amount BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL,
    gateway_ref VARCHAR(64) NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_reconcile_status_id (status, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
