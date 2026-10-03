# slow-query-demo

一个最小可运行的 Spring Boot + MyBatis + MySQL 示例项目，作为「待优化项目」测试数据集的第一个数据单位。项目**故意保留**了典型的慢查询场景，用于复现、诊断并优化 SQL 性能问题。

## 项目概述

- 技术栈：Java 17、Spring Boot 3.2.5、MyBatis 3.0.3、MySQL 8.0、Lombok
- 启动后自动生成 **5 万用户**、**20 万订单**，方便复现慢查询
- 对外暴露一个订单搜索接口 `GET /api/orders/search`

## 目录结构

```text
slow-query-demo
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/OrderController.java
    │   ├── dto/OrderVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/OrderMapper.java      # 慢查询 SQL 核心
    │   ├── model/Order.java
    │   ├── model/User.java
    │   └── service/OrderService.java    # 含 N+1 查询
    └── resources
        ├── application.yml
        └── schema.sql                   # 建表脚本（故意缺索引）
```

## 运行方式

### 1. 启动 MySQL

```bash
docker-compose up -d
```

### 2. 启动项目

```bash
mvn spring-boot:run
```

### 3. 访问慢查询接口

```bash
curl "http://localhost:8080/api/orders/search?email=user1&status=PAID&page=1&size=20"
```

由于 `email=user1` 会匹配 `user1`、`user10`、`user100` 等大量用户，慢查询现象会非常明显。

## 慢查询点分析

| 问题 | 说明 |
| --- | --- |
| `email LIKE '%user1%'` | 前置 `%` 导致 `users.email` 无法使用 B+ 树索引，全表扫描 |
| `o.status = ?` 无索引 | `orders` 表只有 `user_id` 索引，`status` 过滤需要全表扫描 |
| `ORDER BY o.created_at DESC` 无索引 | 产生 `Using filesort` |
| 子查询 `IN (SELECT ...)` | 可能生成临时表，效率低 |
| N+1 查询 | `OrderService` 中每条订单都调用一次 `findUserById` |
| 每次请求都执行 `COUNT()` | 深分页时 count 也很慢 |
| `LIMIT offset, size` | 大 offset 会扫描大量无用行 |
| `SELECT o.*` | 返回不必要字段，无法利用覆盖索引 |

用 `EXPLAIN` 查看原始 SQL，通常可以看到：

```text
type = ALL
rows 很大
Extra = Using where; Using filesort; Using temporary
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    email VARCHAR(128) NOT NULL,
    name VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    order_no VARCHAR(64) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(32) NOT NULL,
    remark VARCHAR(255) DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_orders_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> 注意：`users.email` 无索引，`orders` 缺 `status + created_at` 复合索引——这是慢查询的根本原因之一。

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/orders/search` | `email`（必填）、`status`（必填）、`page`（默认 1）、`size`（默认 20） | 按邮箱模糊匹配 + 订单状态查询订单列表 |

返回结构：

```json
{
  "total": 12345,
  "page": 1,
  "size": 20,
  "list": [
    {
      "orderId": 1,
      "orderNo": "NO1",
      "amount": 100.00,
      "status": "PAID",
      "createdAt": "2025-01-01T12:00:00",
      "userEmail": "user1@example.com",
      "userName": "用户1"
    }
  ]
}
```

## 优化方向提示

1. **加索引**：`users.email` 建索引（若前缀匹配可用），`orders(user_id, status, created_at)` 建复合索引。
2. **改写 SQL**：去掉子查询，改为 `JOIN`，一次查询直接返回 `OrderVO`，消除 N+1。
3. **优化 COUNT**：与主查询同构改写；必要时限制最大页数、缓存总数或改为「加载更多」。
4. **深分页优化**：改用游标分页（基于 `lastCreatedAt`），避免大 offset。
5. **验证**：开启 MySQL 慢查询日志，用 `EXPLAIN` 对比优化前后执行计划。
