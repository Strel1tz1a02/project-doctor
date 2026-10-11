# chunked-response-stream-hold

一个基于 Spring Boot + MyBatis + MySQL 的报表分块导出示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/export/chunked-stream`，按 `chunks` 指定的批大小读取一批报表行，逐行加工后**分块写入 HTTP 响应**（每块写出后立即 flush）并记录导出汇总。

应用启动时会自动初始化测试数据：**export_rows = 20 万**（`segment` 取自 5 个分区）。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java           # 启动类
    │   ├── controller/ExportController.java
    │   ├── dto/ExportStreamSummaryVO.java
    │   ├── init/DataInitRunner.java            # 初始化测试数据
    │   ├── mapper/ExportRowMapper.java         # 数据访问
    │   ├── model/ExportRow.java
    │   └── service/ChunkedExportService.java
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
curl "http://localhost:8080/api/export/chunked-stream?chunks=8000"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/export/chunked-stream` | `chunks`（默认 8000） | 分块读取报表行并以 `text/plain` 分块流式写出 |

响应为 `text/plain` 的逐行文本（每行形如 `segment,amount\n`），服务端在日志中记录导出汇总 `exported` 与 `bytesWritten`。

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS export_rows (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    segment VARCHAR(32) NOT NULL,
    amount BIGINT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_export_segment_id (segment, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
