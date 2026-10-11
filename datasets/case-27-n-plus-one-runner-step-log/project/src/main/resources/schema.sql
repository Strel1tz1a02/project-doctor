CREATE TABLE IF NOT EXISTS jobs (
    job_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    run_id VARCHAR(64) NOT NULL,
    job_name VARCHAR(128) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_jobs_run_id (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS job_steps (
    step_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    job_id BIGINT NOT NULL,
    step_name VARCHAR(128) NOT NULL,
    step_order INT NOT NULL,
    KEY idx_job_steps_job_id (job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS job_logs (
    log_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    job_id BIGINT NOT NULL,
    level VARCHAR(16) NOT NULL,
    message VARCHAR(512) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_job_logs_job_id (job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
