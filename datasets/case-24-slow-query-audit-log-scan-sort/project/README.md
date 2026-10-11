# audit-log-slow-query

一个基于 Spring Boot + MyBatis + MySQL 的审计日志查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/audit/recent`，按日志级别查询最近的审计日志。

应用启动时会自动初始化测试数据：**20 万条审计日志记录**。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/AuditLogController.java
    │   ├── model/AuditLog.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/AuditLogMapper.java   # 数据访问
    │   └── service/AuditLogService.java
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
curl "http://localhost:8080/api/audit/recent?level=ERROR&limit=100"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/audit/recent` | `level`（默认 `ERROR`）、`limit`（默认 `100`） | 返回指定级别最近的 `limit` 条审计日志 |

返回结构：

```json
[
  {
    "id": 199998,
    "serviceName": "order-service",
    "level": "ERROR",
    "message": "event-199998",
    "traceId": "trace-345678",
    "createdAtMs": 1760000000000
  }
]
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    service_name VARCHAR(64) NOT NULL,
    level VARCHAR(16) NOT NULL,
    message VARCHAR(512) NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    created_at_ms BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
