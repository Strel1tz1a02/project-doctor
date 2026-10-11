# job-runner-n-plus-one

一个基于 Spring Boot + MyBatis + MySQL 的任务运行器（Job Runner）查询示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/runner/run-details`，返回某个 run 下最近 job 列表的详情：每个 job 的步骤数与日志数。

应用启动时会自动初始化测试数据：**jobs = 2 万、job_steps = 12 万、job_logs = 24 万**（共 50 个 run，每个 run 400 个 job）。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java    # 启动类
    │   ├── controller/JobRunnerController.java
    │   ├── dto/RunDetailVO.java
    │   ├── dto/RunJobVO.java
    │   ├── dto/JobLogVO.java
    │   ├── init/DataInitRunner.java     # 初始化测试数据
    │   ├── mapper/JobRunnerMapper.java  # 数据访问
    │   ├── model/Job.java
    │   ├── model/JobStep.java
    │   ├── model/JobLog.java
    │   └── service/JobRunnerService.java
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
curl "http://localhost:8080/api/runner/run-details?runId=run-001&limit=200"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/runner/run-details` | `runId`（默认 `run-001`）、`limit`（默认 200） | 返回指定 run 下最近 `limit` 个 job 的步骤数与日志数 |

返回结构：

```json
{
  "jobs": [
    {
      "jobId": 1,
      "jobName": "job-1-1",
      "stepCount": 6
    }
  ],
  "stepTimeline": [
    {
      "jobId": 1,
      "logCount": 12
    }
  ]
}
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS jobs (
    job_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    run_id VARCHAR(64) NOT NULL,
    job_name VARCHAR(128) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_jobs_run_id (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS job_steps (
    step_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    job_id BIGINT NOT NULL,
    step_name VARCHAR(128) NOT NULL,
    step_order INT NOT NULL,
    KEY idx_job_steps_job_id (job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS job_logs (
    log_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    job_id BIGINT NOT NULL,
    level VARCHAR(16) NOT NULL,
    message VARCHAR(512) NOT NULL,
    created_at_ms BIGINT NOT NULL,
    KEY idx_job_logs_job_id (job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
