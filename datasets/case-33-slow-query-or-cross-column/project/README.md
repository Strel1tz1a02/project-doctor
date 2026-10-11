# order-or-scan-slow-query

一个基于 Spring Boot + MyBatis + MySQL 的订单查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/orders/search`，按用户或状态查询订单。

应用启动时会自动初始化测试数据：**30 万条订单记录**。

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
    │   ├── model/Order.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/OrderMapper.java      # 数据访问
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
curl "http://localhost:8080/api/orders/search?userId=1000&status=PAID&limit=50"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/orders/search` | `userId`（默认 `1000`）、`status`（默认 `PAID`）、`limit`（默认 `50`） | 返回指定用户或指定状态的订单，按创建时间倒序 |

返回结构：

```json
[
  {
    "id": 123456,
    "userId": 1000,
    "status": "PAID",
    "amount": 19900,
    "createdAtMs": 1760000000000
  }
]
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL,
    amount BIGINT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_orders_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
