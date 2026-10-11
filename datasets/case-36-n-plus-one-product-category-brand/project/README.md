# product-list-n-plus-one

一个基于 Spring Boot + MyBatis + MySQL 的商品列表示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/products/recent`，返回最近商品列表，每条商品附带所属分类名称与品牌名称。

应用启动时会自动初始化测试数据：**20 万商品、2000 分类、500 品牌**。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/ProductController.java
    │   ├── dto/ProductVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/ProductMapper.java    # 数据访问
    │   ├── model/Product.java
    │   └── service/ProductService.java
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
curl "http://localhost:8080/api/products/recent?size=100"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/products/recent` | `size`（默认 100） | 返回最近商品列表，含分类名与品牌名 |

返回结构（JSON 数组）：

```json
[
  {
    "productId": 199999,
    "name": "product-199999",
    "categoryName": "category-1288",
    "brandName": "brand-87"
  },
  {
    "productId": 199998,
    "name": "product-199998",
    "categoryName": "category-42",
    "brandName": "brand-311"
  }
]
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS categories (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS brands (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS products (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    category_id BIGINT NOT NULL,
    brand_id BIGINT NOT NULL,
    name VARCHAR(140) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_products_created_at (created_at_ms)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
