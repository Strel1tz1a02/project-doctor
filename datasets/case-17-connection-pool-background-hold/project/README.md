# reports-connhold

一个基于 Spring Boot + MyBatis + MySQL 的后台报表任务示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/reports/background`，并发触发指定数量的后台报表任务：每个任务先轮询外部数据源（以 sleep 模拟），再读取最近订单数据并返回统计摘要。

应用启动时会自动初始化测试数据：**orders = 20 万**。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/BackgroundTaskController.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   └── service/BackgroundTaskService.java
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
curl "http://localhost:8080/api/reports/background?tasks=16&pollIntervalMs=800"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/reports/background` | `tasks`（默认 16）、`pollIntervalMs`（默认 800） | 并发运行 `tasks` 个后台报表任务，每个任务轮询 `POLL_ROUNDS=3` 轮、每轮间隔 `pollIntervalMs`，返回各任务摘要 |

返回结构（逐行文本摘要）：

```text
task 1: rows=200
task 2: rows=200
...
task failed: <可选的失败信息>
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    KEY idx_orders_user_created (user_id, created_at),
    user_id BIGINT NOT NULL,
    order_no VARCHAR(64) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(32) NOT NULL,
    remark VARCHAR(255) DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
