# member-lookup-slow-query

一个基于 Spring Boot + MyBatis + MySQL 的会员查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/members/by-no`，按会员号查询单个会员。

应用启动时会自动初始化测试数据：**30 万条会员记录**。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/MemberController.java
    │   ├── model/Member.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/MemberMapper.java     # 数据访问
    │   └── service/MemberService.java
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
curl "http://localhost:8080/api/members/by-no?memberNo=100000001"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/members/by-no` | `memberNo`（默认 `100000001`） | 按会员号返回单个会员 |

返回结构：

```json
{
  "id": 1,
  "memberNo": "100000001",
  "nickname": "grace",
  "level": "GOLD",
  "createdAtMs": 1700000000000
}
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS members (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    member_no VARCHAR(32) NOT NULL,
    nickname VARCHAR(64) NOT NULL,
    level VARCHAR(16) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_members_member_no (member_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
