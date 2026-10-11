# section-list-n-plus-one

一个基于 Spring Boot + MyBatis + MySQL 的课程章节列表示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/sections/recent`，返回最近课程章节列表，每个章节附带所属课程标题与资源数量。

应用启动时会自动初始化测试数据：**20 万章节、5000 课程、40 万资源**。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/SectionController.java
    │   ├── dto/SectionVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/SectionMapper.java    # 数据访问
    │   ├── model/Section.java
    │   └── service/SectionService.java
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
curl "http://localhost:8080/api/sections/recent?size=100"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/sections/recent` | `size`（默认 100） | 返回最近章节列表，含课程标题与资源数 |

返回结构（JSON 数组）：

```json
[
  {
    "sectionId": 199999,
    "title": "section-199999",
    "courseTitle": "course-3182",
    "resourceCount": 2
  },
  {
    "sectionId": 199998,
    "title": "section-199998",
    "courseTitle": "course-77",
    "resourceCount": 1
  }
]
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS courses (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(140) NOT NULL,
    created_at_ms BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sections (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    course_id BIGINT NOT NULL,
    title VARCHAR(140) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_sections_created_at (created_at_ms)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS resources (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    section_id BIGINT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_resources_section_id (section_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
