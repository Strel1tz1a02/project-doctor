# order-dispatch

一个基于 Spring Boot + MyBatis + MySQL 的订单查询与分析示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露三个只读接口：

- `GET /api/orders/by-user`：按用户 ID 返回该用户最近创建的订单列表。
- `GET /api/orders/async-recent`：返回与上一个接口相同的订单列表，差别在于查询任务会提交到应用内的共享调度器（线程池）执行，再取回结果返回。
- `GET /api/orders/analyze`：提交一批耗时的分析/推理任务（每个任务会查询订单并做一段阻塞式计算），等待全部完成后返回汇总结果。

应用启动时会自动初始化测试数据：**20 万订单**（分布在 5 万个用户上）。

## 表象症状

运维工单记录：`GET /api/orders/async-recent` 偶发出现响应变慢（P95 明显升高），尤其在 `GET /api/orders/analyze` 正在运行时更为明显；`analyze` 运行期间反复调用 `async-recent` 会观察到耗时随等待排队而升高。`analyze` 结束后，`async-recent` 的耗时又会回落。单独、空闲状态下调用 `async-recent` 时基线很快。

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
    │   ├── controller/AsyncOrderController.java
    │   ├── dto/OrderVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/OrderMapper.java      # 数据访问
    │   ├── model/Order.java
    │   ├── service/OrderService.java
    │   └── service/AsyncOrderService.java
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
curl "http://localhost:8080/api/orders/by-user?userId=123&size=20"
curl "http://localhost:8080/api/orders/async-recent?userId=123&size=20"
curl "http://localhost:8080/api/orders/analyze?userId=123&rounds=8"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/orders/by-user` | `userId`（必填）、`size`（默认 20） | 按用户 ID 返回其最近创建的订单列表 |
| GET | `/api/orders/async-recent` | `userId`（必填）、`size`（默认 20） | 同上，查询在共享调度器中执行后返回结果 |
| GET | `/api/orders/analyze` | `userId`（必填）、`rounds`（默认 8） | 提交 `rounds` 个阻塞式分析任务，等待全部完成后返回汇总 |

`by-user` / `async-recent` 返回结构：

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

`analyze` 返回结构：

```json
[
  "round-0:50",
  "round-1:50"
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
