# reconcile-long-tx-pool-hold

一个基于 Spring Boot + MyBatis + MySQL 的订单对账示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/reconcile/scan`，扫描一批待对账订单，逐条调用外部支付网关完成结算，并写回结算结果。

应用启动时会自动初始化测试数据：**reconcile_tasks = 20 万**（`order_no` = `ORD-1` … `ORD-200000`，约 60% 为 `PENDING`）。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java           # 启动类
    │   ├── client/PaymentGatewayClient.java    # 外部支付网关客户端（模拟远程调用）
    │   ├── controller/ReconcileController.java
    │   ├── dto/ReconcileResultVO.java
    │   ├── init/DataInitRunner.java            # 初始化测试数据
    │   ├── mapper/ReconcileMapper.java         # 数据访问
    │   ├── model/ReconcileTask.java
    │   └── service/ReconcileService.java
    └── resources
        ├── application.yml
        └── schema.sql                          # 建表脚本
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
curl "http://localhost:8080/api/reconcile/scan?batch=20"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/reconcile/scan` | `batch`（默认 20） | 扫描一批待对账订单，逐条调用支付网关结算并写回结果 |

返回结构（JSON）：

```json
{
  "batchSize": 20,
  "processed": 20
}
```

> 说明：`PaymentGatewayClient.authorize` 在真实环境下会同步发起外部支付网关（HTTP）调用；本示例用固定耗时（250ms）的阻塞调用模拟该远程往返。

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS reconcile_tasks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_no VARCHAR(32) NOT NULL,
    amount BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL,
    gateway_ref VARCHAR(64) NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_reconcile_status_id (status, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
