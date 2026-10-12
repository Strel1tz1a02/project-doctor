# order-report-gain

一个基于 Spring Boot + MyBatis + MySQL 的订单报表聚合示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/orders/report/aggregate`，按订单状态与起始日期统计订单数量与金额，返回聚合结果。

应用启动时会自动初始化测试数据：**orders = 20 万**（随机种子固定，保证可复现）。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/OrderReportController.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   └── mapper/OrderReportMapper.java
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
curl "http://localhost:8080/api/orders/report/aggregate?status=PAID&from=2025-01-01"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/orders/report/aggregate` | `status`（订单状态）、`from`（起始日期） | 统计指定状态、`created_at >= from` 的订单数量与金额合计 |

返回结构（JSON 摘要）：

```json
{ "status": "PAID", "count": 12345, "amountSum": 987654.32 }
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
