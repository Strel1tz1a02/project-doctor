# metrics-aggregate-pool-starve

一个基于 Spring Boot + MyBatis + MySQL 的模型用量指标聚合示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/metrics/aggregate`，聚合遥测事件表 `telemetry_events`：返回事件总数与各模型的计数。

应用启动时会自动初始化测试数据：**telemetry_events = 20 万**（`model-01` … `model-16`）。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/MetricsController.java
    │   ├── dto/MetricsVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/MetricsMapper.java
    │   └── service/MetricsAggregateService.java
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
curl "http://localhost:8080/api/metrics/aggregate?models=16"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/metrics/aggregate` | `models`（默认 16） | 聚合遥测事件：返回事件总数与各模型计数 |

返回结构（JSON）：

```json
{
  "totalEvents": 200000,
  "eventsByModel": {
    "model-01": 12510,
    "model-02": 12488
  }
}
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS telemetry_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    model VARCHAR(32) NOT NULL,
    tokens BIGINT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_telemetry_model (model)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
