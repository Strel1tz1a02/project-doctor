CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    category VARCHAR(32) NOT NULL,
    amount BIGINT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_orders_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
