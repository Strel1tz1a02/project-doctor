# order-synclog

一个基于 Spring Boot + MyBatis + MySQL 的订单查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/orders/audit-report`，按用户 ID 返回该用户最近创建的订单列表，并为每条订单追加一条审计日志。

应用启动时会自动初始化测试数据：**20 万订单**（分布在 5 万个用户上）。

审计日志由 `AuditLogger` 统一写入 `logs/audit.log`：所有写入都在同一把全局锁下串行化，并在持锁期间同步刷盘。

## 已知现象

线上反馈 `GET /api/orders/audit-report` 在 `size` 较大时 P95 明显升高；并发请求越多，单请求耗时越接近「串行叠加」，吞吐上不去；`logs/audit.log` 增长很快。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/OrderController.java
    │   ├── dto/OrderVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── log/AuditLogger.java         # 审计日志门面（全局锁 + 同步刷盘）
    │   ├── mapper/OrderMapper.java      # 数据访问
    │   ├── model/Order.java
    │   └── service/OrderService.java
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
curl "http://localhost:8080/api/orders/audit-report?userId=123&size=500"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/orders/audit-report` | `userId`（必填）、`size`（默认 500） | 按用户 ID 返回其最近创建的订单列表，并逐行追加审计日志 |

返回结构：

```json
[
  {
    "orderId": 1,
    "orderNo": "NO1",
    "amount": 100.00,
    "status": "PAID",
    "createdAt": "2025-01-01T12:00:00"
  }
]
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
