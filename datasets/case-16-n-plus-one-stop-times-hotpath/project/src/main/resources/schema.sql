CREATE TABLE IF NOT EXISTS trips (
    trip_id VARCHAR(64) PRIMARY KEY,
    block_id VARCHAR(64) NOT NULL,
    route_id VARCHAR(64) NOT NULL,
    service_id VARCHAR(64) NOT NULL,
    trip_headsign VARCHAR(128) DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_trips_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stop_times (
    trip_id VARCHAR(64) NOT NULL,
    stop_sequence INT NOT NULL,
    stop_id VARCHAR(64) NOT NULL,
    arrival_time VARCHAR(16) DEFAULT NULL,
    departure_time VARCHAR(16) DEFAULT NULL,
    PRIMARY KEY (trip_id, stop_sequence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stops (
    stop_id VARCHAR(64) PRIMARY KEY,
    stop_name VARCHAR(128) NOT NULL,
    stop_lat DECIMAL(9,6) NOT NULL,
    stop_lon DECIMAL(9,6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
