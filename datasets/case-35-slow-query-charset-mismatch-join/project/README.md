# article-collation-slow-query

一个基于 Spring Boot + MyBatis + MySQL 的文章查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/articles/by-author`，按作者编号查询该作者的文章列表（关联作者名）。

应用启动时会自动初始化测试数据：**5 万条作者记录**、**30 万条文章记录**。

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
    │   ├── dto/ArticleVO.java
    │   ├── model/Article.java
    │   ├── model/Author.java
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
curl "http://localhost:8080/api/articles/by-author?authorCode=A000012"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/articles/by-author` | `authorCode`（默认 `A000012`） | 返回该作者的文章列表（含作者名） |

返回结构：

```json
[
  {
    "id": 8,
    "articleCode": "ART000000008",
    "title": "article-8",
    "authorName": "chen"
  }
]
```

## 数据库表结构（schema.sql）

```sql
-- authors：新系统表，字符集为 utf8mb4
CREATE TABLE IF NOT EXISTS authors (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    author_code VARCHAR(40) NOT NULL,
    name VARCHAR(64) NOT NULL,
    KEY idx_authors_author_code (author_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- articles：从旧系统迁移的历史表，字符集为 utf8mb3（与 authors 不一致）
CREATE TABLE IF NOT EXISTS articles (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    article_code VARCHAR(40) NOT NULL,
    title VARCHAR(200) NOT NULL,
    author_code VARCHAR(40) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_articles_author_code (author_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
```
