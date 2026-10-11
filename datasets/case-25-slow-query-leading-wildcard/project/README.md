# article-search-slow-query

一个基于 Spring Boot + MyBatis + MySQL 的文章标题检索示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/articles/search`，按标题关键字检索文章。

应用启动时会自动初始化测试数据：**20 万篇文章记录**。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/ArticleController.java
    │   ├── model/Article.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/ArticleMapper.java    # 数据访问
    │   └── service/ArticleService.java
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
curl "http://localhost:8080/api/articles/search?keyword=spring&size=20"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/articles/search` | `keyword`（默认 `spring`）、`size`（默认 `20`） | 返回标题包含关键字的最近 `size` 篇文章 |

返回结构：

```json
[
  {
    "id": 199998,
    "title": "spring boot query index mysql #199998",
    "content": "article-body-199998-...",
    "publishedAtMs": 1760000000000
  }
]
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS articles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(256) NOT NULL,
    content VARCHAR(2000) NOT NULL,
    published_at_ms BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
