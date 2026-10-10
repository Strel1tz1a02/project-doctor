# 慢查询预热与锁证据协议

本协议用于串行、单步 GET 索引对照。目的不是保证缓存完全稳定，而是让两组使用同一套可追溯的准备流程。

## 配置

场景声明 `cache.state="warm"`，`cache.preparation_recipe_ref="builtin:serial-readonly-warmup.v1"`。
实验配置 `warmup={"requests_per_level":5}`，`repetitions=10`，请求预算至少为 `2 × (5 + 10) = 30`。

每组依次执行：恢复并验证基线 → 候选组应用索引 → 记录准备指纹 → 5 次预热 → 10 次正式请求 → 核对结束指纹。
正式请求之间不读取全库 dump；全库指纹检查放在组边界，避免污染测量缓存。实验最后仍恢复并验证基线。

预热请求独立记录业务断言、结果摘要、唯一请求 ID、失败与原始制品引用，不参与性能比较。
预热和正式请求均计入请求、时间与制品预算；失败请求仍计费。时间预算保留恢复额度。
任务剩余预算和实验预算共同约束执行。该内置协议不清理应用缓存、不保证其他工作负载的缓存状态。

## 锁证据

正式请求开始前记录 MySQL 版本、consumer/instrument 状态和 history 容量、全局行锁计数及元数据锁计时汇总，并开始采集当前行锁与元数据锁等待。
采样通过请求标记、THREAD_ID 与语句 EVENT_ID 关联；完成后发布能力、原始事件和覆盖说明三份制品。
`LOCK_TIME` 语义：自 MySQL 8.0.28 起，`events_statements_*` 的 `LOCK_TIME` 是逐语句权威锁等待指标，
包含 SQL 表锁与 InnoDB 行锁等待，但不含元数据锁（MDL）等待。demo 隔离镜像用 `mysql:8.4`，故
`LOCK_TIME=0` 即实测表锁与行锁零等待；`LOCK_TIME>0` 即观测到锁等待。

截至 2026-10-10，证据分三种情况：

- 关联到真实等待事件：`observed/partial`，保留原始阻塞证据，不能排除锁因素。
- 采集失败、计时未启用、计数回退或关联缺失：`unknown/partial`，不能声明零等待。
- `LOCK_TIME` 实测（表锁 + InnoDB 行锁）与启用计时的元数据锁汇总完整：可提供完整覆盖。
  表/行锁由 `LOCK_TIME` 实测；元数据锁（MDL）是唯一未测项，用全局 `wait/lock/metadata/sql/mdl` 汇总差值约束。

`LOCK_TIME=0` 且 MDL 汇总无增长 → `covered_no_wait`、`residual_ms=null`、`lock_wait_ms=0`（精确零）。
`LOCK_TIME=0` 且 MDL 汇总有增长 → `covered_no_wait`、`residual_ms=<MDL 界>`（紧致，非整窗口）。
`LOCK_TIME>0` → `observed/complete`，等待值落在 `lock_wait_ms`，MDL 仍以残差约束。
版本 < 8.0.28 时 `LOCK_TIME` 不含行锁，须全局行锁计数前后无增长才可证明行锁零等待，否则拒绝零证明。
完整覆盖表示表/行锁已实测、MDL 已测量或约束，不表示全部耗时为零。全局行锁计数保留在原始制品里作交叉核对，不再作为 8.0.28+ 的零等待门。

诊断比较”实测锁等待 + MDL 残差”和”SQL 收益”：足以解释收益时保持 `lead`；明显小于收益且其余实验门槛满足时，可验证索引访问代价。
微秒级非零 `LOCK_TIME` 不舍入成零，也不直接解释数十毫秒收益。采样空结果本身永远不能证明零等待。

单位：Performance Schema 的计时字段由皮秒换算为毫秒（除以 `1e9`）；`Innodb_row_lock_time` 本身为毫秒。官方定义见 [语句事件表](https://dev.mysql.com/doc/refman/8.0/en/performance-schema-events-statements-current-table.html) 与 [服务器状态变量](https://dev.mysql.com/doc/refman/8.4/en/server-status-variables.html)。

旧记录仍可读取，但缺实际准备记录或完整锁覆盖时只能作为 lead。
正式结论需重复至少 3 次；两组 IQR 各不超过 `max(中位数×0.25, 0.5ms)`；耗时中位差严格超过 `max(1ms, 两组 IQR 之和)`。该策略已由此前更新改为 IQR，本次没有放宽数值门槛。

## 环境与验证

应用和数据库仅连接内部网络；独立入口仅在 `127.0.0.1` 发布端口，固定转发到 app:8080。

```powershell
docker build -t project-doctor-target:latest demo/slow-query-demo
docker build -t project-doctor-ingress:latest demo/ingress
$env:PATH = 'C:\Program Files\Docker\Docker\resources\bin;' + $env:PATH
$env:PROJECT_DOCTOR_TARGET_REPO = (Resolve-Path demo/slow-query-demo).Path
$env:PROJECT_DOCTOR_LOCK_CONTROLS = '1'
./scripts/check.ps1
```

真实 MySQL 存储回环需额外提供 `PROJECT_DOCTOR_PLATFORM_DSN`，仅通过本地私有配置传入。
锁阳性测试建立独立、无端口、无外部网络的临时 MySQL 容器，测试后清理；不使用评估数据。
MySQL JSON 记录使用 `model_dump(mode="json")`，以保留锁证据的时区时间。
