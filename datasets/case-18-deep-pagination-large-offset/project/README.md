# items-deeppage

一个基于 Spring Boot + MyBatis + MySQL 的商品分页查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/items/page`，按 `offset`/`limit` 分页返回商品列表。

应用启动时会自动初始化测试数据：**120 万条 item 记录**。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/ItemController.java
    │   ├── dto/ItemVO.java
    │   ├── dto/PageVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/ItemMapper.java       # 数据访问
    │   ├── model/Item.java
    │   └── service/ItemService.java
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
curl "http://localhost:8080/api/items/page?offset=170000&limit=20"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/items/page` | `offset`（默认 0）、`limit`（默认 20） | 按位移分页返回商品列表 |

返回结构：

```json
{
  "offset": 170000,
  "limit": 20,
  "total": 1200000,
  "items": [
    {
      "itemId": 170001,
      "name": "item-170001",
      "category": "BOOK",
      "price": 1234500.00,
      "createdAt": "2026-03-01T10:20:30"
    }
  ]
}
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(128) NOT NULL,
    category VARCHAR(64) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_items_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
