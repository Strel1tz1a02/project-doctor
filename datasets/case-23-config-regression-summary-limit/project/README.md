# order-summary

一个基于 Spring Boot + MyBatis + MySQL 的订单查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露两个只读接口：

- `GET /api/orders/by-user`：按用户 ID 返回该用户最近创建的订单列表。
- `GET /api/orders/summary`：返回最近创建的订单摘要列表；返回行数由配置项
  `report.summary.limit` 控制，解析逻辑见 `config/SummaryLimitResolver`，
  约定摘要行数落在 `[1, HARD_MAX]` 区间内。

应用启动时会自动初始化测试数据：**20 万订单**（分布在 5 万个用户上）。

## 表象症状

`GET /api/orders/summary` 返回的行数明显偏大：

- 该接口本应受摘要上限约束（约百余行），但当前一次请求会返回约 5000 行；
- 接口不报错、HTTP 状态码 200；
- 数据库侧该查询为 `ORDER BY id DESC LIMIT n`、走主键、执行计划正常；
- `/api/orders/by-user` 一切正常，耗时与返回行数均无异常。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java        # 启动类
    │   ├── config/SummaryLimitResolver.java # 摘要行数上限解析
    │   ├── controller/OrderController.java
    │   ├── dto/OrderVO.java
    │   ├── init/DataInitRunner.java         # 初始化测试数据
    │   ├── mapper/OrderMapper.java          # 数据访问
    │   ├── model/Order.java
    │   └── service/OrderService.java
    └── resources
        ├── application.yml
        └── schema.sql                       # 建表脚本
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
curl "http://localhost:8080/api/orders/by-user?userId=123&size=20"
curl "http://localhost:8080/api/orders/summary"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/orders/by-user` | `userId`（必填）、`size`（默认 20） | 按用户 ID 返回其最近创建的订单列表 |
| GET | `/api/orders/summary` | 无 | 返回最近创建的订单摘要列表，行数由配置 `report.summary.limit` 决定 |

返回结构（两个接口一致）：

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
