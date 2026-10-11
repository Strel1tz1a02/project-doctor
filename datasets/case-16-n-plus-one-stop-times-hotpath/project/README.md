# trips-stop-times-nplus1

一个基于 Spring Boot + MyBatis + MySQL 的公交行程/停靠点（GTFS 风格）查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/trips/block-details`，返回最近行程列表的区块详情：每个行程的前后相邻行程、所属 block 的行程序列，以及每个行程的停靠点数量。

应用启动时会自动初始化测试数据：**trips = 5 万、stop_times = 50 万、stops = 5000**。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/BlockTripController.java
    │   ├── dto/AdjacentTripVO.java
    │   ├── dto/BlockTripVO.java
    │   ├── dto/BlockDetailVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/TripMapper.java       # 数据访问
    │   ├── model/Trip.java
    │   ├── model/StopTime.java
    │   └── service/BlockTripService.java
    └── resources
        ├── application.yml
        └── schema.sql                   # 建表脚本
```

## 运行方式

### 1. 启动 MySQL

```bash
docker compose up -d mysql
```

### 2. 启动应用

```bash
mvn spring-boot:run
```

### 3. 调用接口

```bash
curl "http://localhost:8080/api/trips/block-details?size=200"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/trips/block-details` | `size`（默认 200） | 返回最近 `size` 个行程的区块详情 |

返回结构：

```json
{
  "adjacentTrips": [
    {
      "tripId": "T12345",
      "blockId": "B42",
      "stopCount": 10,
      "previousTripId": null,
      "nextTripId": "T12346"
    }
  ],
  "blockSequences": [
    {
      "tripId": "T12345",
      "blockSequence": 1,
      "stopCount": 10
    }
  ]
}
```

## 数据库表结构（schema.sql）

```sql
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
```
