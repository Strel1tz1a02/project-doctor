# feed-timeline-n-plus-one

一个基于 Spring Boot + MyBatis + MySQL 的内容动态流示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/feed/recent`，返回最近动态列表，每条动态附带作者昵称与点赞数。

应用启动时会自动初始化测试数据：**5 万用户、20 万条动态、40 万条点赞**。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/FeedController.java
    │   ├── dto/FeedItemVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/FeedMapper.java       # 数据访问
    │   ├── model/Post.java
    │   └── service/FeedService.java
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
curl "http://localhost:8080/api/feed/recent?size=100"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/feed/recent` | `size`（默认 100） | 返回最近动态列表，含作者昵称与点赞数 |

返回结构（JSON 数组）：

```json
[
  {
    "postId": 199999,
    "content": "post-199999",
    "authorNickname": "user-32101",
    "likeCount": 2
  },
  {
    "postId": 199998,
    "content": "post-199998",
    "authorNickname": "user-1888",
    "likeCount": 1
  }
]
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS posts (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    author_id BIGINT NOT NULL,
    content VARCHAR(140) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_posts_created_at (created_at_ms)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    nickname VARCHAR(64) NOT NULL,
    created_at_ms BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS likes (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    post_id BIGINT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_likes_post_id (post_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
