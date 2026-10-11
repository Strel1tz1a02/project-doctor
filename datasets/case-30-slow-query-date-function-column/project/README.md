# audit-day-function-slow-query

一个基于 Spring Boot + MyBatis + MySQL 的审计日志按天查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/audit/events/by-day`，按日期查询当天的审计事件。

应用启动时会自动初始化测试数据：**30 万条审计事件记录**（近 180 天）。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/AuditController.java
    │   ├── model/AuditEvent.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/AuditEventMapper.java # 数据访问
    │   └── service/AuditEventService.java
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
curl "http://localhost:8080/api/audit/events/by-day?day=2025-06-10&size=20"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/audit/events/by-day` | `day`（默认 `2025-06-10`）、`size`（默认 `20`） | 返回指定日期最近的 `size` 条审计事件 |

返回结构：

```json
[
  {
    "id": 271034,
    "actor": "alice",
    "action": "LOGIN",
    "occurredAtMs": 1749520000000
  }
]
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS audit_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    actor VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    occurred_at_ms BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
