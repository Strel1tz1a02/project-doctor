# admin-stats-n-plus-one

一个基于 Spring Boot + MyBatis + MySQL 的后台订单统计示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/admin/stats`，按分类统计订单数量与金额。

应用启动时会自动初始化测试数据：**20 万条订单记录**，分布在 100 个分类中。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/AdminStatsController.java
    │   ├── dto/StatsVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/OrderStatsMapper.java # 数据访问
    │   └── service/OrderStatsService.java
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
curl "http://localhost:8080/api/admin/stats"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/admin/stats` | 无 | 返回订单总数、各分类订单数与各分类金额 |

返回结构：

```json
{
  "totalOrders": 200000,
  "orderCountByCategory": {
    "cat-001": 1995,
    "cat-002": 2010
  },
  "amountByCategory": {
    "cat-001": 10048,
    "cat-002": 9971
  }
}
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    category VARCHAR(32) NOT NULL,
    amount BIGINT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_orders_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
