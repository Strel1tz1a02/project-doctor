# orders-reconcile

一个基于 Spring Boot + MyBatis + MySQL 的订单对账示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/orders/reconcile`，对指定天数范围内的订单做对账聚合（排序 + 按状态分组统计金额），返回对账摘要。

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
    │   ├── controller/ReconcileController.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   └── service/ReconcileService.java
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
curl "http://localhost:8080/api/orders/reconcile?days=90"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/orders/reconcile` | `days`（默认 90） | 对最近 `days` 天的订单做对账聚合，返回按状态分组的金额合计 |

返回结构（JSON 摘要）：

```json
{ "days": 90, "groups": [ { "status": "PAID", "count": 30000, "amountSum": 2400000.00 } ] }
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    KEY idx_orders_created_at (created_at),
    user_id BIGINT NOT NULL,
    order_no VARCHAR(64) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(32) NOT NULL,
    remark VARCHAR(255) DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> 说明：`application.yml` 中的 `hikari.maximum-pool-size: 20` 与 `connection-timeout: 3000` 为连接池环境参数。
