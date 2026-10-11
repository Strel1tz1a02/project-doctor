# order-batchsetup

一个基于 Spring Boot + MyBatis + MySQL 的订单查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露两个接口：

- `GET /api/orders/by-user`：按用户 ID 返回该用户最近创建的订单列表（走 MyBatis）。
- `GET /api/orders/legacy-batch`：**遗留批处理报表接口**，返回最近创建订单的简表文本（`id,orderNo,amount`），供旧版批量报表下载使用。

应用启动时会自动初始化测试数据：**20 万订单**（分布在 5 万个用户上）。

## 已知现象

线上反馈 `GET /api/orders/legacy-batch` 在并发压力下 P95 偏高（明显高于 `by-user`），
且请求量升高时数据库连接数出现较大波动；返回的数据量本身很小，单条 SQL 执行很快。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java                 # 启动类
    │   ├── controller/OrderController.java           # /api/orders/by-user
    │   ├── controller/LegacyBatchReportController.java# /api/orders/legacy-batch
    │   ├── dto/OrderVO.java
    │   ├── init/DataInitRunner.java                  # 初始化测试数据
    │   ├── mapper/OrderMapper.java                   # 数据访问
    │   ├── model/Order.java
    │   ├── service/OrderService.java                 # by-user 业务逻辑
    │   └── service/LegacyBatchReportService.java     # 批处理报表业务逻辑
    └── resources
        ├── application.yml
        └── schema.sql                                # 建表脚本
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
curl "http://localhost:8080/api/orders/legacy-batch?size=50"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/orders/by-user` | `userId`（必填）、`size`（默认 20） | 按用户 ID 返回其最近创建的订单列表 |
| GET | `/api/orders/legacy-batch` | `size`（默认 50） | 返回最近创建订单的简表文本 |

`by-user` 返回结构：

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

`legacy-batch` 返回结构（纯文本，每行一条）：

```text
200000,NO200000,1234.00
199999,NO199999,5678.00
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
