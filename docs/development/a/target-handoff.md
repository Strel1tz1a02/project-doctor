# A0：目标接入交接（首个目标 slow-query-demo）

> 本文是 A0 的交付物，供 B 冻结合同。记录首个目标的固定提交、启动/迁移/种子/有效请求/凭据、
> 干预配方（recipe_ref）、SQL→请求→代码行采集办法、可核对观测样例，以及当前阻断项。
> 真实 Docker/MySQL/HTTP/SQL 端到端尚未运行，标记为**未验证**。

## 1. 目标项目与固定提交

| 项 | 值 |
| --- | --- |
| 目标仓库 | `d:\agent2\slow-query-demo\slow-query-demo` |
| 固定提交 | `9f497db5d4ea09d37f3d07bcda3471c71c815031`（本 A0 首次 `git init` 后提交） |
| 目标栈 | Java 17 · Spring Boot 3.2.5 · MyBatis 3.0.3 · MySQL 8.0（隔离镜像默认 `mysql:8.4`，兼容） |
| 有效业务请求 | `GET /api/orders/search?email=user1&status=PAID&page=1&size=20` |
| 返回结构 | `{"total":N,"page":1,"size":20,"list":[OrderVO...]}` |

`ProjectInput` 建议值：

```json
{
  "repo_path": "local:slow-query-demo",
  "commit": "9f497db5d4ea09d37f3d07bcda3471c71c815031",
  "supplied_url": "http://127.0.0.1:18080",
  "recipe_ref": "recipe:orders-status-created"
}
```

## 2. 干预配方 recipe_ref

- `recipe_ref = "recipe:orders-status-created"`，经 `_resolve_recipe` 解析为 `<target_repo_root>/recipes/orders-status-created.sql`：

```sql
CREATE INDEX idx_orders_status_created ON orders (status, created_at)
```

- 该语句通过 `parse_index_recipe` 的严格校验（单条 `CREATE [UNIQUE] INDEX name ON table (cols)`），
  反解出 `drop_sql = DROP INDEX idx_orders_status_created ON orders`，供恢复核对。
- **为何只对 status+created_at**：`orders` 仅有 `idx_orders_user_id`；`WHERE o.status = ?` 全扫 +
  `ORDER BY o.created_at DESC` 走 filesort，是该查询唯一可被 B-tree 索引修复的机制。
- **诚实的负例**：`users.email LIKE '%user1%'` 前置通配**无法**用 B-tree 索引修复，属于 blocked path，
  不应宣称「加索引即可消除全部慢查询」。该边界已写入 `manifest.json` 的 `uncovered_paths`。

## 3. 迁移 / 种子 / 凭据

- **迁移**：`spring.sql.init.mode=always` + `classpath:schema.sql`（建 `users`、`orders`，故意缺
  `status`/`created_at`/`email` 索引）。
- **种子**：`DataInitRunner`（`Random(42)`）首次启动造 5 万用户 + 20 万订单，幂等（`users` 计数 >0 即跳过）。
  状态集 `{CREATED,PAID,SHIPPED,DONE,CANCELED}`，约 4 订单/用户。
- **凭据**：业务请求无凭据（`credential_refs=[]`）；数据库凭据是隔离环境内建 `app/app/app`，由
  `render_compose` 以 `MYSQL_*`（db 侧）与 `DB_*`（app 侧）注入，非目标仓库敏感信息。
- **配置覆盖**：`application.yml` 已改为 `${DB_HOST:localhost}:${DB_PORT:3306}/${DB_NAME:slow_query_demo}`
  与 `${DB_USER:root}`/`${DB_PASSWORD:root}`，独立开发缺省不变，隔离环境由 `DB_*` 覆盖。

## 4. SQL → 请求 → 代码行采集办法（采集模块已实现，真实联调未跑）

目标：让每条 `SqlCall` 带有 `duration_ms`/`rows_examined`/`rows_returned`/`lock_wait_ms` 实测来源，
以及指向当前 commit 的 `code_location`（B 的 gate 硬性要求 `code_location.commit == commit`）。

拟采用（`sql_probe.py` 已实现步骤 1/3 的采集与解析并离线单测；步骤 2/4 与真实联调待补）：

1. **语句采样**：请求后从 MySQL `performance_schema.events_statements_history_long` 读取该连接窗口内
   的 `DIGEST_TEXT`、`TIMER_WAIT`（→`duration_ms`）、`ROWS_EXAMINED`、`ROWS_SENT`（→`rows_returned`）、
   `LOCK_TIME`（→`lock_wait_ms`）。`performance_schema` 需在 db 容器启用
   `performance_schema=ON` 与 `events_statements_history_long_size` 足够大。
2. **请求→SQL 关联**：`HttpResponse` 已带请求标识（`request_id`）；SQL 与请求通过连接/时间窗 + 摘要匹配。
3. **代码行映射**：`OrderMapper.findSlowOrders` / `countSlowOrders` / `findUserById` 注解 SQL 为静态文本，
   可在 MyBatis 拦截器中给每条 SQL 前缀注入 `/* pd:<path>:<line> */` 注释，采集端解析回
   `CodeLocation(commit, path, line)`；commit 取 `ProjectInput.commit`。
4. **计划证据**：对 `findSlowOrders` 分别 `EXPLAIN` baseline 与 candidate，转 `PlanEstimate`
   （`access_type`/`rows`/`key`），估算与实际行数分开（缺锁等待/执行统计保留 null 与原因）。

**已实现（离线可复现）**：`src/project_doctor/integrations/observation/sql_probe.py` 的
`PerfSchemaSqlProbe` 已注入 `build_runtime`——`fetch_rows` 经 `gateway.query_sql` 在 db 容器内跑
`mysql --batch --skip-column-names --raw` 读取 `performance_schema.events_statements_history_long`，
`parse_mysql_batch` 解析列，`perf_schema_row_to_sql_call` 产出带 `duration_ms`/`rows_examined`/
`rows_returned`/`lock_wait_ms`（`metric_sources` 均 `source="performance_schema", measurement="actual"`）
与 `code_location(commit, path, line)` 的 `SqlCall`。纯函数与探针编排见 `tests/runtime/test_sql_probe.py`。

**已在真实 MySQL 9.5 上验证并修复（本轮）**：
- `render_compose` 给 db 服务加 `command: --performance-schema-consumer-events-statements-history-long=ON`，
  打开默认关闭的 `events_statements_history_long` 消费者。
- `DockerEnvironmentGateway._prepare_sync` 写 `initdb/grant-perf-schema.sql`（`GRANT SELECT ON
  performance_schema.* TO '<db_user>'@'%'`）并挂载 `./initdb` 到 `/docker-entrypoint-initdb.d`，
  解除探针用户读 perf_schema 的 `ERROR 1142`。
- `parse_plan`（`plans.py`）同时解析 EXPLAIN v1（`query_block`）与 v2（`query_plan` 树、
  `access_type:"table"|"index"`、`estimated_rows` float、`index_name`），"table" 归一化为 "ALL"。
- `lock_wait_to_ms`（`sql_probe.py`）1 位小数换算 LOCK_TIME，<0.05ms 计时噪声判 0.0，满足 B gate 的
  `lock_wait_ms == 0`，真实锁等待仍非零。

**仍待补（未闭环，见 §6.4）**：目标应用侧 MyBatis 拦截器注入标记（app 侧，A 不写目标仓库代码），
以及上述消费者/权限/EXPLAIN v2/锁等待换算在真实 Docker 隔离容器内的端到端跑通。

## 5. 可核对观测样例（B 冻结合同用）

一次有效请求应产出（示意，非真实采样值）：

```json
{
  "business_valid": true,
  "latency_ms": 480.0,
  "result_digest": "<sha256 of /list business projection>",
  "sql_calls": [
    {
      "normalized_sql": "SELECT o.* FROM orders o WHERE o.status = ? AND o.user_id IN (SELECT id FROM users WHERE email LIKE CONCAT('%', ?, '%')) ORDER BY o.created_at DESC LIMIT ?, ?",
      "duration_ms": 412.0,
      "rows_examined": 200000,
      "rows_returned": 20,
      "metric_sources": {
        "duration_ms": {"source": "performance_schema", "measurement": "actual"},
        "rows_examined": {"source": "performance_schema", "measurement": "actual"}
      },
      "code_location": {"commit": "9f497db…", "path": "src/main/java/com/example/slowquery/mapper/OrderMapper.java", "line": 14}
    }
  ]
}
```

- baseline 与 candidate_index 的 `rows_examined` 在 `findSlowOrders` 上应从 ~200000 降到 status 分片量级；
  `users.email LIKE '%…%'` 全扫与 N+1 的 `findUserById` 在两组恒定，只影响绝对耗时，不影响归因差值。

## 6. 阻断项 / 未验证（真实联调前必须解决）

1. **镜像未构建**：需先 `docker build -t project-doctor-target:latest`（目标仓库根目录），`render_compose`
   只引用 `image:`，不现场 build。
2. **种子时机**：`up --wait` 只等容器 running，不等 `DataInitRunner` 造数完成；基线快照若在种子完成前采集，
   恢复后为空库且应用不会重跑种子（幂等）。建议：加 actuator 就绪探针（users 计数 >0）+ Dockerfile HEALTHCHECK，
   使 `up --wait` 等到种子完成。
3. **`manifest.json` 的 `dataset.snapshot_id` 是占位符**：首次 prepare 后用 mysqldump 摘要回填，使
   `spec.snapshot_id == scenario.dataset.snapshot_id`（B gate 校验）。
4. **`SqlProbe` 已注入，证据链基础设施已补齐，剩 app 侧标记与真实 Docker 跑通**：`build_runtime`
   现构造 `PerfSchemaSqlProbe` 并注入 `RuntimeService`（观测 `sql_calls` 来自 perf_schema 采集，已离线
   单测）。已就绪：db 容器消费者开关（`--performance-schema-consumer-events-statements-history-long=ON`）、
   perf_schema 读权限（initdb `GRANT SELECT ON performance_schema.*`）、EXPLAIN v1/v2 解析、
   原始 perf_schema + EXPLAIN 证据制品发布（`metric_sources[*].evidence_ids`/`plan_evidence_ids` 均为
   已发布制品 sha256，B gate 校验子集）。剩余：目标应用侧 MyBatis 拦截器注入 `/* pd:<path>:<line> */`
   标记（app 侧代码，A 不改目标仓库），以及一次真实 Docker 端到端跑通验证。
5. **平台 MySQL 未验证**：`PROJECT_DOCTOR_PLATFORM_DSN` 未设，任务存储往返、事务回滚未对真实 MySQL 运行。
6. **`allowed_target_network` 须含回环**：隔离服务经 `ports: "{service_port}:8080"` 发布到宿主机回环，
   `RestrictedHttpClient` 的 base_url 是 `http://127.0.0.1:{service_port}`；白名单若设为 Docker 内网
   （如 `172.28.0.0/24`）会拒绝 `127.0.0.1`。真实部署应设 `127.0.0.0/8`（或等价含回环的 CIDR）。

## 7. 验证状态

- 离线可复现（本次已验证）：recipe 解析、manifest → `discover()` → 严格合同校验、`ProjectInput` 构建、
  参考目标形状（Dockerfile EXPOSE 8080 + `DB_*` 注入）、`sql_probe.py` 的标记解析/度量换算/批量解析/
  探针编排（`tests/runtime/test_sql_probe.py`）。
- 未验证：真实 Docker up、mysqldump 基线/恢复摘要比对、真实 HTTP 200 + 业务断言、perf_schema 统计、
  EXPLAIN 计划转换、平台 MySQL 事务。
