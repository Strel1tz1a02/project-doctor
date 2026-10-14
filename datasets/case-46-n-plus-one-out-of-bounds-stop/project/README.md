# article-recent-nplus1

一个基于 Spring Boot + MyBatis + MySQL 的文章查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/articles/recent`，返回**最近创建的文章列表**，并在每篇文章上附带**作者的姓名与邮箱**。

应用启动时会自动初始化测试数据：**20 万篇文章**（分布在 5 万个作者上）。

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
    │   ├── dto/ArticleVO.java           # 文章返回对象（含作者信息）
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/ArticleMapper.java    # 数据访问（部分语句以注解定义）
    │   ├── model/Article.java
    │   ├── model/Author.java
    │   └── service/ArticleService.java
    └── resources
        ├── application.yml
        ├── mapper/ArticleMapper.xml     # 数据访问（部分语句以 XML 定义）
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
curl "http://localhost:8080/api/articles/recent?size=200"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/articles/recent` | `size`（默认 200） | 返回最近创建的文章列表，并附带作者姓名与邮箱 |

返回结构：

```json
[
  {
    "articleId": 1,
    "title": "文章1",
    "status": "PUBLISHED",
    "createdAt": "2025-01-01T12:00:00",
    "authorName": "author1",
    "authorEmail": "author1@example.com"
  }
]
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS authors (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(64) NOT NULL,
    email VARCHAR(128) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS articles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    author_id BIGINT NOT NULL,
    title VARCHAR(200) NOT NULL,
    status VARCHAR(32) NOT NULL,
    summary VARCHAR(255) DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_articles_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
