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

正式请求开始前记录 MySQL 版本、consumer/instrument 状态和 history 容量，并开始采集当前行锁与元数据锁等待。
采样通过请求标记、THREAD_ID 与语句 EVENT_ID 关联；完成后发布能力、原始事件和覆盖说明三份制品。
语句历史中的非零 LOCK_TIME 也可证明观测到部分锁等待。

当前实现只能返回 `observed` 或 `unknown`，覆盖为 `partial`，实际总锁等待时长为 null。
请求后空的 data_lock_waits 快照、采样间没有事件、非零值舍入均不能证明零等待。
完整零等待合同保留给能够证明全过程覆盖的采集器；本采集器不生成 `covered_no_wait`。

旧记录仍可读取，但缺实际准备记录或完整锁覆盖时只能作为 lead。
正式结论仍需满足重复至少 3 次、相对极差不超过 0.25、耗时中位差严格超过 1ms 和两组极差之和等原有门槛。

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
