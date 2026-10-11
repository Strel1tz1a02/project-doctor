# pool-growth-discard

一个基于 Spring Boot 的入库示例服务，内置一个按需异步扩容的简化数据库连接池。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/pool/ingest`，并发运行指定数量的入库工作任务：每个任务从内置连接池借用连接执行一次计数查询，并模拟一段处理耗时后归还，最终返回成功/超时/失败统计。

应用启动时会自动初始化测试数据：**task_events = 20 万**（`shard` 0..15）。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java
    │   ├── config/PoolConfig.java          # 构建内置连接池
    │   ├── controller/PoolIngestController.java
    │   ├── dto/IngestResultVO.java
    │   ├── init/DataInitRunner.java        # 初始化测试数据
    │   ├── pool/SimpleConnectionPool.java  # 按需异步扩容的简化连接池
    │   └── service/PooledIngestService.java
    └── resources
        ├── application.yml
        └── schema.sql                      # 建表脚本
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
curl "http://localhost:8080/api/pool/ingest?workers=16"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/pool/ingest` | `workers`（默认 16） | 并发运行 `workers` 个入库任务，每个任务从连接池借用连接查询并模拟处理，返回统计 |

返回结构（JSON）：

```json
{
  "workers": 16,
  "success": 16,
  "timedOut": 0,
  "failed": 0,
  "elapsedMs": 340,
  "allocated": 6,
  "maxSize": 12
}
```

## 连接池配置（application.yml）

连接池由 `SimpleConnectionPool` 实现，按需异步扩容，参数在 `app.pool` 下配置：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `app.pool.max-size` | 12 | 池连接数上限 |
| `app.pool.queue-capacity` | 2 | 扩容执行器队列容量 |
| `app.pool.queue-threads` | 1 | 扩容执行器线程数 |
| `app.pool.borrow-timeout-ms` | 3000 | 借用连接的最长等待时间 |
| `app.pool.hold-millis` | 200 | 单个任务借用连接期间模拟的处理耗时 |

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS task_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    shard INT NOT NULL,
    status VARCHAR(16) NOT NULL,
    payload_size INT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_task_events_shard (shard)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
