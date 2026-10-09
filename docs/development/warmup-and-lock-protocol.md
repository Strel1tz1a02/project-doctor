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
语句历史中的非零 LOCK_TIME 也可证明观测到部分锁等待。

截至 2026-10-09，证据分三种情况：

- 关联到真实等待事件：`observed/partial`，保留原始阻塞证据，不能排除锁因素。
- 采集失败、计时未启用、计数回退或关联缺失：`unknown/partial`，不能声明零等待。
- 表锁 `LOCK_TIME`、全局行锁计数和启用计时的元数据锁汇总均完整：可以提供完整覆盖或保守的累计耗时上界。行锁计数前后无增长且两端无活跃等待时排除行锁；元数据锁汇总差值约束该语句的元数据锁耗时；表锁时间采用语句实际值。

只有全部锁证据支持精确零值时，才同时输出 `covered_no_wait`、`residual_ms=null`、实际 `lock_wait_ms=0`。
存在非零表锁耗时，使用 `observed/complete` 并保留累计上界；只有元数据锁上界或行锁采样上界时也保留 `residual_ms`，实际总 `lock_wait_ms=null`。
完整覆盖表示全部锁类别均已测量或约束，不表示全部耗时为零。缺少行锁精确计数保证时，累计未观测等待以上下文整个采集窗口为界；50ms 轮询间隔不是累计等待上界。

诊断比较“锁累计上界”和“SQL 收益”：上界足以解释收益时保持 `lead`；上界明显小于收益且其余实验门槛满足时，可验证索引访问代价。
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
