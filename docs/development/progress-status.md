# Project Doctor 开发进度与任务规划

> 主体截至 2026-10-05；2026-10-09 增量结果见 [锁证据与终态修复](acceptance/2026-10-09-lock-finish-evaluation-repair.md) 和 [COUNT 反例与边界修复](acceptance/2026-10-09-count-boundary-repair.md)。本文按比赛要求整理「已做了什么 → 怎么实现 → 后续任务」，
> 作为团队内部进度总览与参赛材料的基础。详细证据见文末「关联文档」。

2026-10-10 按用户要求，诊断源码已恢复到六例串行评估版本 `agh-suite-20261009-round2`，
78 个源文件 SHA-256 全部匹配。保留锁证据、终态报告、COUNT 反例与边界修复。
后加的源码绑定、AGH 启动器和持续 HTTP 负载代码已归档，不作为当前功能。
恢复范围和验证见 [串行版本恢复](acceptance/2026-10-10-serial-version-restoration.md)。

此前 [源码与会话修复](acceptance/2026-10-09-source-session-load-repair.md)、
[持续负载实现](acceptance/2026-10-09-timed-load.md) 与 [持续负载评估](acceptance/2026-10-09-live-timed-evaluation.md)
保留为历史记录。最新一轮六例诊断 1/6 不作为恢复后版本的新成绩；用户限定只评诊断、不评修正。

恢复后 [六例串行诊断复跑](acceptance/2026-10-10-serial-diagnosis-rerun.md) 已完成：
六例均完成实验，业务工具错误 0；诊断评分 3/6，误验证 1，整轮未通过。
case-04 成功 verified；case-05 错误升级 verified；case-03 虽通过但输出 lead 高于预期，属于评估门槛缺口。

## 1. 项目与比赛要求

**赛事**：2026 年江苏省 AI+ 科学与工程创新实践黑客松（本科组）。
统一命题：**用 AI 完成一项可执行、可验证的科学、工程或设计任务**，须形成
「问题理解—任务规划—工具调用—执行反馈—调整纠错—结果验证」的完整流程。

**硬性约束**（提交前必须满足）：

- 所有模型调用仅限 **Agnes 模型**，不得接入第三方模型。
- 必须使用 **Agnes Harness（AGH）** 作为智能体运行底座，且 AGH 必须在**核心任务流程**中发挥实际作用，不能只生成说明文字。
- 至少调用一项外部能力（数据 / 代码 / 数据库 / 专业软件 / 仿真 / API / 设备）。
- 有明确的结果验证方法，并展示至少一次**异常 / 失败 / 边界**处理过程。
- 提交「项目说明、可运行作品、3–5 分钟演示视频、可核查的 AGH 执行记录、正常/边界/失败三类测试样例、独立完成声明」。

**时间节点**：作品提交 10 月 7 日–15 日 12 时；线上评审 10 月 16–18 日。

**选题**：后端项目性能诊断 Agent（Project Doctor）——输入一个后端代码仓库与测试地址，
平台自行创建可重置的隔离副本，结合代码线索与受控运行实验，定位性能瓶颈并输出
**具体 SQL、触发代码位置、原始证据和可验证的修改建议**。

**首版范围**：慢查询 / 有代价的全表扫描、N+1 查询、深分页。
**当前交付口径**：只完成「慢查询」诊断到 JSON/HTML 报告；N+1、深分页后续安排。
不自动改代码、不做生产压测、不宣称任意技术栈可深度诊断。

## 2. 总体架构与分工

**技术栈**：Python 3.13 + Pydantic 2.13（数据合同）· MySQL（业务存储）·
Docker Compose（隔离环境）· httpx（受限请求）· 官方 Python MCP SDK（工具入口）·
AGH + Agnes 模型（诊断主循环）· pytest / Ruff / mypy（验证）。

**分层**（依赖单向、不循环）：

```text
entrypoints    MCP 入口 + 实例组装
workflows      任务、实验执行、恢复、收尾的业务编排
features       environments / scenarios / experiments / diagnosis / reports 规则
integrations   mysql / docker / http / observation / artifacts 外部实现
models         统一数据合同、引用与错误类型（不依赖其他层）
```

**双人分工**：

| 线 | 责任 | 产物 |
| --- | --- | --- |
| A（运行时/基础设施） | A0 目标接入、A1 持久化、A2 隔离环境、A3 慢查询测量、A4 中断核对 | `integrations/`、`runtime_factory.py`、`workflows/execute_experiment.py`、`reconcile.py` |
| B（合同/诊断/报告） | 数据模型、场景 manifest、诊断门槛、报告、MCP 工具 | `models/`、`features/diagnosis/`、`features/reports/`、`workflows/tools.py` |
| 第三人 | 正式评估数据集 | `datasets/`（已上传，开发修复不修改案例或评分器） |

**三个公共协议**（B 定义、A 实现）：

- `Runtime`（`features/experiments/ports.py`）：prepare / run / close 执行与预算结算。
- `TaskStore`（`workflows/task_ports.py`）：任务、操作、实验、假设、结论的持久化。
- `EvidenceReader`（`features/diagnosis/ports.py`）：核对制品文件、hash、大小与目录边界。

## 3. 已完成内容

### 3.1 P0 公共基线（合同与骨架）

- **v0.1 数据模型**：`Scenario`、`ExperimentSpec`、`Observation`、`Hypothesis`、`Finding`、
  `SqlCall`、`LockEvidence`、`ReportData` 等；未知字段拒绝、耗时用 ms、行号从 1 起。
- **合同测试**：`tests/contracts/` 共 41 项；39 份 JSON Schema 由代码生成（禁止手改）。
- **六组合同样例**：verified_slow_query + 缺位置/缺文件/不可比/恢复失败/未知结果五组反例。
- **配置与检查入口**：`config/settings.example.json`、`scripts/check.ps1`。

### 3.2 场景发现与诊断判据（B）

- **显式场景 manifest**（`features/scenarios/discover.py`）：从 manifest 读取场景，
  不做任意仓库的自动路由/OpenAPI 解析；`uncovered_paths` 显式记录未覆盖路径（N+1、深分页等）。
- **慢查询判据**（`features/diagnosis/gates.py` + `compare.py`）：保守门槛，证据不足只输出 lead。
- **MeasurementPolicy**：重复 ≥3；组内 IQR ≤ max(0.25×中位数, 0.5ms)；耗时中位差 > max(1ms, 两组 IQR 之和)。1ms 是差异门槛，不是业务 SLA。
- **报告**（`features/reports/`）：影响排序 + 诊断卡 + JSON + HTML 渲染。

### 3.3 运行时与基础设施（A，A0–A4）

- **A0 目标接入**：首个目标 `slow-query-demo`（Spring Boot 3.2.5 + MyBatis，固定提交 `9f497db`），
  干预配方 `recipe:orders-status-created`（单条 `CREATE INDEX`），`demo/reference/manifest.json`。
- **A1 持久化**（`integrations/mysql/task_store.py`）：`MySQLTaskStore` 实现 TaskStore 全部 10 个方法；
  reserve 靠数据库唯一键幂等，finish_operation 单事务结算（操作更新 + dispatch + 预算），终态提前返回。
- **A2 隔离环境**（`integrations/docker/`）：`DockerEnvironmentGateway` + `ComposeRunner` + `SnapshotManager`；
  专用 compose 项目名防串环境；指纹 `sha256(commit, snapshot_id)`；恢复仅当 mysqldump 摘要匹配基线且临时索引已移除才判 verified。
- **A3 慢查询测量**（`runtime_factory.py`）：`RuntimeService.prepare/run/close` + `_settle`（预留→执行→结算）
  持有环境独占；受限 HTTP 白名单 + 业务断言 + 观测转换 + 制品发布。
- **A4 中断核对**（`workflows/reconcile.py`）：`classify_operation` 分 completed / safe_same_input / needs_reconcile，
  不盲目重放副作用，未知操作保留并隔离环境。

### 3.4 观测采集（SQL + 锁 + 预热）

- **SQL 探针**（`integrations/observation/sql_probe.py`）：从 `performance_schema.events_statements_history_long`
  读取带标记的语句，解析出 `duration_ms` / `rows_examined` / `rows_returned` 与 `code_location(commit, path, line)`，
  并为每条 SQL 生成 `EXPLAIN FORMAT=JSON` 计划制品。
- **锁证据**（`integrations/observation/lock_probe.py` + `models/lock.py`）：请求期间采样
  `data_lock_waits`（InnoDB 行锁）与 `metadata_locks`（元数据锁），按 request_id / THREAD_ID / EVENT_ID 关联，
  产出 `LockEvidence`（status `observed`/`covered_no_wait`/`unknown`，coverage `complete`/`partial`/`unknown`）。
  **零等待来自 `LOCK_TIME` 实测（表锁 + InnoDB 行锁），MDL 用全局汇总差值约束；空快照绝不等于零等待。**
- **预热流程**（`features/experiments/preparation.py`）：每组「恢复基线 → 应用索引 → 记录准备指纹 →
  N 次预热 → 正式测量」，预热与正式请求分开记录、都计预算。

### 3.5 目标演示项目 slow-query-demo

- **栈**：Java 17 · Spring Boot 3.2.5 · MyBatis 3.0.3 · MySQL 8.4（隔离镜像 `mysql:8.4`）。
- **数据**：`Random(42)` 种子 5 万用户 + 20 万订单（`DataInitRunner` 幂等，`/tmp/ready` 就绪标记）。
- **有效请求**：`GET /api/orders/search?email=user1&status=PAID&page=1&size=20`。
- **SQL 标记**：MyBatis 拦截器（`SqlCommentInterceptor`）+ `RequestIdFilter` + `RequestContext`
  给每条 SQL 前缀注入 `/* pd:<路径>:<行号> request=<32 位十六进制 ID> */`，
  使采集端能把 SQL 归属到本次请求与具体代码行。

### 3.6 MCP 工具（8 个）

`create_task` · `prepare_environment` · `discover_scenarios` · `propose_hypotheses` ·
`run_experiment` · `evaluate_evidence` · `reconcile_task` · `finish_task`。
每个工具在 `agh/tool-policy.json` 声明超时、副作用与可重放条件（重放策略 business_key / version_key / reconcile_first）。

## 4. 关键实现机制（怎么做对的）

1. **证据 ID = 内容寻址**：制品 sha256 即 evidence id，路径为 `stem-{digest}.json`；同一内容跨路径不会产生冲突元数据。
2. **SQL → 请求 → 代码行关联**：应用侧注入 `pd` 标记（含请求 ID 与行号），采集端 `_CODE_MARKER` 正则解析，
   `code_location.commit` 严格等于 `ProjectInput.commit`（B gate 硬性要求）。
3. **诚实的锁覆盖**：`LOCK_TIME` 是逐语句权威锁等待指标（MySQL 8.0.28+ 含表锁与 InnoDB 行锁，不含 MDL），
   直接写入 `SqlCall.lock_wait_ms`；MDL 是唯一未测项，由独立 `lock_probe` 用全局汇总差值约束，落在
   `residual_ms`，未覆盖或版本 < 8.0.28 无法证明行锁时保持保守，让诊断按门槛降级为线索。
4. **波动门槛**：`stable()` 用 `(max-min)/median <= 0.25`（含边界）；`distinguishable()` 要求
   中位差严格超过 `max(1ms, 两组噪声)`；与评估双阈值（验收 0.25、复测 0.10）对齐。
5. **隔离与恢复**：compose 项目名隔离、指纹绑定提交+快照、恢复后验证 mysqldump 摘要一致且临时索引已移除，
   失败即隔离环境并停止依赖实验。
6. **预算与幂等**：reserve 以唯一键幂等，同 ID 同输入返回已有结果、同 ID 不同输入冲突、状态不明先 reconcile；
   终态提前返回避免重复扣预算。
7. **参数内联保计划忠实**：MySQL Connector/J 客户端预编译默认关闭，SQL 值被内联（无 `?`），
   因此 `EXPLAIN` 计划对应真实请求参数，而非占位符计划。

## 5. 验证状态（截至 2026-10-05）

| 层级 | 结果 |
| --- | --- |
| 静态套件 `scripts/check.ps1` | **227 passed, 7 skipped**；Ruff 检查/格式、mypy（strict，78 源文件）全通过 |
| 真实 MySQL 存储回环 | 通过（task store 往返、幂等 reserve、单事务结算、锁窗口 JSON 时区回环） |
| Docker 端到端 | 通过（compose up → 基线快照 → 一次请求 → 恢复 → 摘要校验） |
| 锁阳性对照 | 通过（独立临时 MySQL 上真实行锁/元数据锁阳性，测后删除） |
| 完整慢查询业务链路 | **跑通**：10 预热 + 20 正式样本 + 30 独立请求 ID；440 条 SQL 调用、536 份证据制品，大小/SHA-256 全核对；JSON/HTML 报告已生成 |

**真实链路的关键结论（诚实负例）**：主查询 `OrderMapper.java:14` 在 baseline 与 candidate_index 的
扫描行数中位数都是 **94732**，耗时中位数 108.13 / 95.93 ms——当前索引配方**没有降低扫描工作量**，
差异也未过波动门槛，因此诊断**保留为 lead（线索）**，而非 verified。这证明系统在证据不足时克制下结论，
而不是把「加索引」硬写成已修复。

**尚未验证（最大缺口）**：

- **AGH 模型自主诊断**：`agh/tool-policy.json` 仍为 `declared_not_integrated`；真实链路中
  MCP 工具选择由**联调脚本指定**，AGH 模型尚未真正发起并消费工具结果。
- **官方 SDK 协议已通、scripted 流程已通**，但这两者都不能替代真实 AGH 模型调用。

## 6. 后续任务（按优先级）

### P0（比赛硬性要求，提交前必须）

1. **接通真实 AGH 诊断主循环**：AGH 加载 Agnes 模型 → 经 MCP 调用 8 个业务工具 → 自主
   提出假设、选择实验、评估证据、决定下一步；导出可核查的 AGH 执行记录（会话 + 工具调用）。
   这是当前与「基本完成要求」之间最大的鸿沟。
2. **准备比赛提交材料**：项目说明（模型名称/版本/使用环节/调用方式）、3–5 分钟演示视频、
   AGH 执行记录、正常/边界/失败三类测试样例、独立完成声明。

### P1（补全首版承诺的诊断能力）

3. **N+1 查询诊断**：`demo` 的 `findUserById` 已能采集到 N+1 语句与代码行，缺的是
   N+1 的证据门槛与判据（`features/diagnosis/`）。
4. **深分页诊断**：大 OFFSET 的判定与证据门槛。

### P2（演示效果与评估）

5. **构造一个能「verified」的正例**：当前慢查询的 `email LIKE '%…%'` 前置通配 + N+1 结构
   使单索引无法降低扫描，导致只能出 lead。需要一个干预确实降低访问工作量的场景/配方，
   演示「已验证」的完整闭环（建议、复测、报告）。
6. **正式评估数据集**：由第三人负责，A/B 只维护最小联调种子与开发测试样例。

### P3（收尾与工程）

7. **修复/复验遗留边界**：真实 AGH 链路下的中断恢复、预算结算完整性（观测制品计入）、
   受控 recipe 引用路径校验等已在验收文档中列出的待办。
8. **开源准备**（若入围）：代码库、配置模板、README、复现说明、第三方依赖与许可证。

## 7. 关联文档

- 设计：[产品整体设计](../superpowers/specs/2026-09-30-backend-performance-diagnosis-agent-design.md) ·
  [平台架构设计](../superpowers/specs/2026-10-02-platform-architecture-design.md)
- 基线/交接：[P0 公共基线](p0-baseline.md) · [B → A 交接](b/handoff-to-a.md) · [A0 目标交接](a/target-handoff.md)
- 测试：[P1 初版测试日志](p1-first-version-test.md) · [预热与锁证据协议](warmup-and-lock-protocol.md)
- 验收：[2026-10-02 首交付验收](acceptance/2026-10-02-project-acceptance.md) ·
  [2026-10-05 修复验收](acceptance/2026-10-05-evidence-and-isolation-repair.md)
- 规则：[参赛指南](../比赛规则/2026年江苏省AI+科学与工程创新实践黑客松_【高校组】 参赛指南.md)
