# threads-max-timestamps

一个基于 Spring Boot + MyBatis + MySQL 的线程元数据聚合示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/threads/max-timestamps`，返回 `threads` 表中线程更新时间戳与最近活动时间戳的最大值。

应用启动时会自动初始化测试数据：**20 万条 thread 记录**。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/ThreadController.java
    │   ├── dto/ThreadTimestamps.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/ThreadMapper.java     # 数据访问
    │   └── service/ThreadService.java
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
curl "http://localhost:8080/api/threads/max-timestamps"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/threads/max-timestamps` | 无 | 返回线程最大更新时间戳与最大最近活动时间戳 |

返回结构：

```json
{
  "maxUpdatedAtMs": 1760000000000,
  "maxRecencyAtMs": 1759900000000
}
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS threads (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(128) NOT NULL,
    updated_at_ms BIGINT NOT NULL,
    recency_at_ms BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
