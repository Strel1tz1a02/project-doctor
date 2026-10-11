# provider-releases

一个基于 Spring Boot + MyBatis + MySQL 的发布信息查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露发布信息查询接口：

- `GET /api/providers/releases`：返回发布信息表中的全部记录。
- `GET /api/providers/releases/latest`：按 provider 返回该来源最近的发布记录（不含 payload）。

应用启动时会自动初始化测试数据：**5000 条发布记录**（分布在 5 类 provider 上，每条含约 6 KB 的 `payload` JSON）。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java          # 启动类
    │   ├── controller/ProviderReleaseController.java
    │   ├── dto/ProviderReleaseVO.java
    │   ├── init/DataInitRunner.java           # 初始化测试数据
    │   ├── mapper/ProviderReleaseMapper.java  # 数据访问
    │   ├── model/ProviderRelease.java
    │   └── service/ProviderReleaseService.java
    └── resources
        ├── application.yml
        └── schema.sql                         # 建表脚本
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
curl "http://localhost:8080/api/providers/releases"
curl "http://localhost:8080/api/providers/releases/latest?provider=signal&size=20"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/providers/releases` | 无 | 返回发布信息表中的全部记录（含完整 `payload`） |
| GET | `/api/providers/releases/latest` | `provider`（必填）、`size`（默认 20） | 按 provider 返回其最近的发布记录 |

`GET /api/providers/releases` 返回结构：

```json
[
  {
    "id": 1,
    "provider": "signal",
    "releaseTag": "v0.1.0",
    "payload": "{\"release\":1,\"assets\":[{\"asset\":\"release-asset\",\"size\":1048576,...}]}",
    "createdAt": "2025-01-01T12:00:00"
  }
]
```

`GET /api/providers/releases/latest` 返回结构：

```json
[
  {
    "releaseId": 1,
    "provider": "signal",
    "releaseTag": "v0.1.0",
    "createdAt": "2025-01-01T12:00:00"
  }
]
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS provider_releases (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    provider VARCHAR(64) NOT NULL,
    release_tag VARCHAR(128) NOT NULL,
    payload LONGTEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_provider_releases_provider (provider)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
