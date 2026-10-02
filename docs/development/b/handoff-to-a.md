# B → A：慢查询联调交接

## 授权的兼容补充

2026-10-02 用户确认：在 `ExperimentResult` 新增可选 `spec: ExperimentSpec | None = None`。
原 v0.1 JSON 仍可读取；新 Schema 已生成，旧记录缺 spec 时只输出 lead。
A.run 需要把实际执行且校验过的 spec 持久化并返回，不能由模型在 evaluate_evidence 时补写。
spec.id 必须与 experiment_id 相同；task_id、场景 ID／版本、基线指纹、快照、观测配置及索引配方需要真实对应。

## A 需要完成的接口约束

- `build_store(settings)`、`build_runtime(settings, store)`、`build_evidence_reader(settings)` 为同步构造工厂；运行操作仍为异步。
- TaskStore.get 缺任务抛 KeyError；create 需要数据库唯一键下幂等创建，同 ID 不同内容冲突，不能依靠先查后写防并发。
- prepare 持久记录 task.environment_id 并进入 running；B 后续只读取，不自行修改环境记录。
- run 负责预留／结算预算、幂等、网络及配方限制、环境独占、实际采集、恢复与持久化。B 不再次 reserve 或 finish_operation。
- B 首条规则支持每次重复一个有效业务请求，每组至少三次。多步骤场景可以存储，但本轮诊断门槛会降级多请求／多同模板调用，避免误归因。
- baseline 指纹等于 spec.baseline_fingerprint；candidate_index 同组指纹固定，唯一允许差异是该配方的索引变化。
- 各组快照／观测配置必须一致；result_digest 是脱敏规范化业务结果的摘要，两组相同；request_id 每次测量唯一。
- 每个 SQL 提供实际 duration_ms／rows_examined，以及零锁等待的真实 lock_wait_ms；缺失值 null。未知锁等待不会当成零。
- code_location 的 commit 对应 task.project.commit；关联证据、统计来源和计划 evidence ID 均必须存在于结果证据引用中。
- restore_result 的指纹／快照回到 spec 基线并有原始证据；失败或未明确完成不能返回假成功，实际环境应隔离。
- EvidenceReader.verify 必须实际核对文件、hash、大小和目录边界；B 只通过此接口检查制品，当前不解析计划私有格式。
- save_scenario 按 ID／版本 upsert；save_findings 和 save_hypotheses 按 ID upsert。B 会保存旧结论降级记录，防止历史 verified 绕过收尾核对。
- close 与 publish_report 接收不同派生业务键 `原 operation_id:close`、`原 operation_id:report`，原 AGH 关联标识保留。

## 当前判据的真实语义

程序支持的结论是“在本次固定条件下，索引干预降低 SQL 的实际访问工作量与耗时”。
不会单凭存在 plan 文件判 type=ALL，不会把索引干预有效直接写成“所有慢查询都因为缺索引”。
报告保留计划引用供复核；目标数据库计划解析仍归 A。统计或条件不足，B 输出 lead 和具体缺项。
比较策略默认重复≥3、组内相对极差≤0.25、耗时中位差>1ms 且超过两组极差之和；这些是可配置实施策略，不是业务 SLA。

## 验证入口

```powershell
uv sync --locked
./scripts/check.ps1
uv run --locked project-doctor-mcp --settings config/settings.local.json --manifest config/manifest.local.json
```

manifest 格式为 `{"scenarios": [Scenario 数据合同], "uncovered_paths": ["未覆盖路径"]}`。
目前 B1 接收仓库文档／测试／路由推导后的显式场景 manifest；不声称已实现任意仓库的自动路由／OpenAPI 解析。
MCP 生产入口仅装配真实 A 工厂，缺失时明确退出；测试假实现只在 tests 下。

联调完成前，官方 SDK 协议测试与 scripted B 流程仅证明 B 边界行为，不代表实际环境、MySQL 或 AGH 模型调用已经验证。
