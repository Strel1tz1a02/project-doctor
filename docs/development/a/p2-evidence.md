# A → B：首轮运行时联调证据与状态

## 本阶段完成范围（A0–A4）

- **A0 目标接入探针**：选定 `slow-query-demo` 为首个目标并固定提交 `9f497db`；补 Dockerfile（多阶段构建、EXPOSE 8080、读 `DB_*` 环境变量）、`application.yml` 环境变量驱动、`recipes/orders-status-created.sql`；产出 `docs/development/a/target-handoff.md`（recipe_ref、栈版本、SQL→代码行采集办法、可核对观测样例、阻断项）与 `demo/reference/`（`manifest.json` + Dockerfile + recipes）。真实 HTTP/SQL/恢复端到端待 Docker 就绪后运行（`test_target_probe.py` 已 skip-gated）。
- **A1 持久化**：`MySQLTaskStore` 实现全部 10 个 TaskStore 方法；status 列为唯一状态真源，其余字段存版本化 JSON 摘要列；reserve 幂等靠唯一键，finish_operation 单事务结算（操作更新 + dispatch + 预算），终态提前返回避免重复扣预算。
- **A2 隔离环境**：`DockerEnvironmentGateway` + `ComposeRunner` + `SnapshotManager`；专用 Compose project 名（`compose_project_name`）防串环境；指纹 `sha256(commit, snapshot_id)`；`restore_verified` 仅当恢复摘要匹配基线且临时索引已移除才判 verified。
- **A3 慢查询测量**：`RuntimeService.prepare/run/close` + `_settle`（预留→执行→结算）持有环境独占；受限 HTTP 白名单 + 断言 + 观测转换 + 制品发布；索引配方只接受单条 `CREATE [UNIQUE] INDEX`，拒绝任意 DDL。`SqlProbe`（`PerfSchemaSqlProbe`）已注入 `build_runtime`：经 `gateway.query_sql` 读 `performance_schema` 标记语句，`parse_mysql_batch`/`perf_schema_row_to_sql_call` 产出带实测来源与 `code_location(commit,path,line)` 的 `SqlCall`。
- **A4 中断核对**：`classify_operation`（有结果=completed；仅 reserved 无结果=safe_same_input；否则 needs_reconcile）；`reconcile` 不重放副作用，未知操作保留并隔离环境。

## 已验证（本机可复现，非真实环境）

- `ruff check`、`ruff format --check`、`mypy`（strict）全部通过。
- `pytest` 共 172 passed（1 个失败为 B 的过期用例，见「已知交接事项」；3 skipped 为真实依赖未就绪）；
  A 侧纯逻辑与脚本化联调断言覆盖：
  - A0 目标探针离线断言：recipe 解析、manifest → discover → 严格合同校验、`ProjectInput` 构建、参考目标形状（Dockerfile/配方文件）；
  - compose 名/指纹/渲染、恢复判定、URL 拼接、白名单、断言评估、EXPLAIN 解析、代码位置绑定；
  - SqlProbe 标记解析/度量换算（picoseconds→ms）/批量解析/探针编排（`tests/runtime/test_sql_probe.py`）；
  - 慢查询两水平各三次测量、预算耗尽拒绝、环境不匹配拒绝、请求失败仍恢复且保留部分观测；
  - 中断核对 completed/safe_same_input/needs_reconcile 及未知操作隔离。

## 已对真实 MySQL 验证

- **平台 MySQL 连接/事务**：本机已装 MySQL 9.5（`C:\Program Files\MySQL\MySQL Server 9.5\`，端口 3306），建库 `project_doctor` + 专用用户 `pd`。`tests/integration/runtime/test_store.py::test_store_round_trip` 在设置 `PROJECT_DOCTOR_PLATFORM_DSN` 后 **8/8 通过**，真实表结构、幂等 reserve、单事务结算、回滚均已对真实 MySQL 验证。

## 真实 MySQL 联调发现（已修复，见对应代码）

1. **`events_statements_history_long` 消费者默认关闭**：MySQL 8.4/9.x 默认仅启用 `events_statements_current`/`events_statements_history`，`..._history_long` 为 `NO`，探针查询返回空。已修：`render_compose` 给 db 服务加 `command: --performance-schema-consumer-events-statements-history-long=ON`。
2. **探针 db 用户缺 `performance_schema` 读权限**：`MYSQL_USER` 只授 `app.*`，读 `events_statements_history_long` 报 `ERROR 1142`。已修：`DockerEnvironmentGateway._prepare_sync` 写 `initdb/grant-perf-schema.sql`（`GRANT SELECT ON performance_schema.* TO '<db_user>'@'%'`）并挂载 `./initdb` 到 `/docker-entrypoint-initdb.d`。
3. **EXPLAIN FORMAT=JSON v2 格式不兼容**：MySQL 8.4/9.x 返回 `json_schema_version:"2.0"`（`query_plan` 树、`access_type:"table"|"index"`、`estimated_rows` 为 float、`index_name`），旧 `parse_plan` 只认 v1 `query_block.table`。已修：`parse_plan` 同时解析 v1/v2（"table" 归一化为 "ALL"、float 行数转 int、`index_name`→`key_used`），新增 `tests/runtime/test_observation.py` 两个 v2 用例。
4. **`LOCK_TIME` 计时粒度噪声**：实测 `LOCK_TIME=2000000ps`（≈2µs，MDL/计时噪声），换算后 `lock_wait_ms=0.002`，而 B gate 要求 `lock_wait_ms == 0`。已修：新增 `lock_wait_to_ms`（1 位小数），<0.05ms 判 0.0，真实锁等待（≥ms 级）仍非零，不改 `duration_ms` 的 3 位精度。

## 未验证（真实依赖缺失，记为未验证）

- **Docker 恢复**：真实容器恢复（`mysqldump` 摘要比对、`docker compose down -v`）未运行；`test_restore.py` 用脚本化 runner/snapshot 双假验证编排与判定，非真实恢复。Docker 安装被阻断（非管理员、无 WSL2、无 winget），需手工提权，见 `target-handoff.md` §6。
- **真实 HTTP/SQL 采集端到端**：`test_slow_query.py` 用假网关/假 HTTP/假 store 验证编排；真实请求、perf_schema 统计、EXPLAIN 计划转换未对隔离容器运行。`SqlProbe` 已注入，且 §真实 MySQL 联调发现 中的消费者开关、权限、EXPLAIN v2 解析已在真实 MySQL 上各自验证；剩余待真实 Docker 跑通的是目标应用侧 MyBatis 拦截器注入 `/* pd:path:line */` 标记与完整证据链闭环。
- **A0 真实目标探针**：`test_target_probe.py::test_target_probe_end_to_end` 因无 docker 而 skip（未验证）。需先 `docker build -t project-doctor-target:latest` 并设 `PROJECT_DOCTOR_TARGET_REPO` 指向目标仓库；同时注意种子时机与 `allowed_target_network` 须含回环（详见 `target-handoff.md` §6）。
- **AGH 模型调用**：全部模型调用待接入，本阶段无。

## 已知交接事项

- **B 的 `test_bootstrap.py::test_missing_a_factory_does_not_silently_fall_back_to_fake` 现失败**。该测试的前提是「A 工厂缺失时 bootstrap 应抛错」；三个工厂（store/runtime/reader）现已全部就位，测试前提不再成立，`bootstrap` 走到 `resolve_secret_ref` 抛「platform secret 未设置」。此文件归 B，A 不改；建议 B 将该测试改为断言「工厂已就位但平台 DSN 缺失时报错」或删除该过期用例。
- `publish_report` 只发布 B 已渲染的 JSON/HTML，不在 A 复制报告规则。

## 验证入口

```powershell
uv sync --locked
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked mypy
uv run --locked pytest -q
```

真实 MySQL/Docker 联调需补 `PROJECT_DOCTOR_PLATFORM_DSN` 与目标仓库，届时运行 `tests/integration/runtime/test_store.py`、`test_restore.py`、`test_slow_query.py` 并替换脚本化双假为真实实现。
