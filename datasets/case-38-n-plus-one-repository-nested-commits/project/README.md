# repository-nested-n-plus-one

一个基于 Spring Boot + MyBatis + MySQL 的代码仓库提交汇总示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/repositories/recent`，返回最近活跃仓库列表，每个仓库附带其提交列表，每条提交附带提交者名称。

应用启动时会自动初始化测试数据：**2 万仓库、20 万提交、5 万提交者**。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/RepositoryController.java
    │   ├── dto/RepositoryVO.java
    │   ├── dto/CommitVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/RepositoryMapper.java # 数据访问
    │   ├── model/Repository.java
    │   ├── model/Commit.java
    │   └── service/RepositoryService.java
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
curl "http://localhost:8080/api/repositories/recent?size=20"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/repositories/recent` | `size`（默认 20） | 返回最近仓库列表，含提交列表与提交者名称 |

返回结构（JSON 数组）：

```json
[
  {
    "repositoryId": 19999,
    "name": "org-812/repo-19999",
    "commits": [
      {
        "commitId": 199999,
        "message": "commit-199999",
        "committerName": "committer-3182"
      },
      {
        "commitId": 199998,
        "message": "commit-199998",
        "committerName": "committer-77"
      }
    ]
  }
]
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS committers (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS repositories (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    owner VARCHAR(64) NOT NULL,
    name VARCHAR(140) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_repositories_created_at (created_at_ms)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS commits (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    repository_id BIGINT NOT NULL,
    committer_id BIGINT NOT NULL,
    message VARCHAR(200) NOT NULL,
    KEY idx_commits_repository_id (repository_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
