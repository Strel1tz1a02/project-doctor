# report-cursor-stream-hold

一个基于 Spring Boot + MyBatis + MySQL 的报表导出示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/reports/stream-export`，以 MyBatis 游标（`Cursor`）流式读取一批报表行，逐行做字段加工后汇总导出长度。

应用启动时会自动初始化测试数据：**report_rows = 20 万**（`region` 取自 5 个区域，`metric` 取自 5 个指标）。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java           # 启动类
    │   ├── controller/ReportController.java
    │   ├── dto/ReportExportResultVO.java
    │   ├── init/DataInitRunner.java            # 初始化测试数据
    │   ├── mapper/ReportRowMapper.java         # 数据访问（游标流式读取）
    │   ├── model/ReportRow.java
    │   └── service/ReportExportService.java
    └── resources
        ├── application.yml
        └── schema.sql                          # 建表脚本
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
curl "http://localhost:8080/api/reports/stream-export?limit=20000"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/reports/stream-export` | `limit`（默认 20000） | 流式读取一批报表行并逐行加工导出 |

返回结构（JSON）：

```json
{
  "limit": 20000,
  "exported": 20000,
  "outputLength": 812345
}
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS report_rows (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    region VARCHAR(32) NOT NULL,
    metric VARCHAR(32) NOT NULL,
    amount BIGINT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_report_region_id (region, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
