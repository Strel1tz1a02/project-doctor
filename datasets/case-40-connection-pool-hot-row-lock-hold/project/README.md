# counter-hot-row-lock-hold

一个基于 Spring Boot + MyBatis + MySQL 的计数器示例服务。

## 技术栈

- Java 17
- Spring Boot 3.2.5
- MyBatis 3.0.3
- MySQL 8.0
- Lombok

## 功能

对外暴露接口 `GET /api/counters/increment`，对一个计数键（默认 `CNT-1`）执行「加锁读取当前值 → 重算窗口 → 写回」的原子自增并返回新值。

应用启动时会自动初始化测试数据：**counters = 20 万**（`counter_key` 形如 `CNT-1`..`CNT-200000`）。

## 目录结构

```text
.
├── pom.xml
├── docker-compose.yml
├── README.md
└── src/main
    ├── java/com/example/slowquery
    │   ├── SlowQueryApplication.java           # 启动类
    │   ├── controller/CounterController.java
    │   ├── dto/CounterResultVO.java
    │   ├── init/DataInitRunner.java            # 初始化测试数据
    │   ├── mapper/CounterMapper.java           # 数据访问
    │   ├── model/Counter.java
    │   └── service/CounterService.java
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
curl "http://localhost:8080/api/counters/increment?key=CNT-1"
```

## 接口说明

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/counters/increment` | `key`（默认 `CNT-1`） | 对指定计数键执行加锁自增并返回新值 |

返回结构（JSON）：

```json
{
  "counterKey": "CNT-1",
  "value": 42
}
```

## 数据库表结构（schema.sql）

```sql
CREATE TABLE IF NOT EXISTS counters (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    counter_key VARCHAR(64) NOT NULL,
    value BIGINT NOT NULL,
    updated_at_ms BIGINT NOT NULL,
    UNIQUE KEY uk_counter_key (counter_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
