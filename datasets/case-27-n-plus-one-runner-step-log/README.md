# case-27-n-plus-one-runner-step-log

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `n_plus_one` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自 [gabrielkoerich/orch](https://github.com/gabrielkoerich/orch) Issue #1407（`source=adapted`，许可证待核验） |

设计意图：任务运行器需要为某个 run 的最近 job 列表附带每个 job 的**步骤数**与**日志数**。项目先查询一次 job 列表，再在 `for` 循环中**逐 job 分别查询 `job_steps` 与 `job_logs`**（N+1，合计 `2N+1` 次数据库往返）。单条查询按 `idx_job_steps_job_id` / `idx_job_logs_job_id` 走索引、执行计划本身无问题，缺陷在于**调用次数随 job 条数线性增长**。用例考察 Agent 是否能：

1. 把根因定位到「循环中的逐条查询」（N+1），而非任何单条 SQL 的执行计划；
2. 认识到 `n_plus_one` 现虽由 Agent 的 `ProblemKind` 支持，但本用例未纳入「逐条 vs 批量」判别实验与批量改造后复测增益等结构化证据，故维持 `lead`；
3. 不虚构不存在的索引类根因（避免 `false_verified`）。

## 上游来源与原汁原味的保留

- 上游：`gabrielkoerich/orch` Issue #1407（许可证待核验）。
- 上游版本：`main@d565d944559632eee4f021d0fb367ae78be3e87f`。
- 保留的原汁原味：上游任务运行器在 `src/engine/runner/context.rs` 的 run 上下文构建（约 79-109 行）中对每个 job 逐条查询其 steps 与 logs，形成 `2N+1` 次数据库往返。
- 按数据集约定的改造：技术栈统一为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；保留「先取 job 列表，再在循环中逐 job 查询 steps 与 logs」的 `2N+1` 语义，并映射为 `JobRunnerMapper.findStepsByJobId` / `findLogsByJobId`；表名 `jobs` / `job_steps` / `job_logs` 与列名 `job_id` / `run_id` / `step_order` / `level` 保持不变。上游许可证尚未核验，`provenance.license` 标注为「待核验」，不臆断。

## 目录结构

```text
case-27-n-plus-one-runner-step-log/
├─ case.json                # 问题卡（ground truth）
├─ README.md                # 本文件（含答案，隔离）
└─ project/                 # 被测项目（Spring Boot + MyBatis + MySQL），唯一暴露给 Agent 的目录
   ├─ pom.xml
   ├─ docker-compose.yml
   ├─ README.md             # 面向 Agent 的项目说明（已脱敏）
   └─ src/main/...
```

## 缺陷清单

`path` 均相对 `project/`。

| defect_id | role | kind | 位置 | 期望状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `d1` | primary | `n_plus_one` | `.../service/JobRunnerService.java:35` | `lead` | `buildJobViews` 先取 job 列表（1 次）再逐 job 调用 `findStepsByJobId`（N 次）；单条按 `idx_job_steps_job_id` 走索引，问题在于调用次数 |
| `d2` | secondary | `n_plus_one` | `.../service/JobRunnerService.java:48` | `lead` | `buildStepTimeline` 第二个循环逐 job 调用 `findLogsByJobId`，与 d1 同源，合计 `2N+1`；primary 仍定位在 steps 循环 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 2 万 job / 12 万 job_steps / 24 万 job_logs）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/runner/run-details?runId=run-001&limit=200"
```

## 评估要点

- `decision_match = exact`（期望 `lead`，Agent 不得给出 `verified`）。
- `root_cause_recall`：命中 `d1` 即视为召回主根因；`d2` 属同源次要。
- `false_verified = false`：Agent 若宣称 `verified`（例如声称「已加索引证实」）即判失败。
- `limitation_declared`：须命中 `case.json` 中 `expected.limitations_required` 的 3 条声明（判定依据、`n_plus_one` 已支持但证据不足维持 `lead`、依赖列表页大小）。
- `reward_profile = boundary_composite`，`timeout_seconds = 2400`。
- 该缺陷**不能**由平台单变量索引实验证实；本用例亦未纳入「逐条 vs 批量」判别实验与改造复测增益证据，故整体期望 `lead`。
- **边界设定说明**：`n_plus_one` 现已由 Agent 的 `ProblemKind` 支持，本用例维持 `lead` 是数据集刻意的边界设定（未纳入足以闭环的判别实验与改造增益证据）；具备完整证据链的同类用例（如 `case-07`）可产出 `verified`。

## 与其它用例的关系

- 与 `case-16-n-plus-one-stop-times-hotpath`、`case-26-n-plus-one-category-count-loop` 同为 `n_plus_one` / boundary / `lead`，但场景不同：`case-16` 是「行程热路径逐条查 StopTimes」、`case-26` 是「后台统计逐分类聚合」、本用例是「run 上下文逐 job 查 steps/logs（sibling 双循环）」。
- 与 `case-07-n-plus-one-order-user`（`n_plus_one`）互为正交样本，覆盖「父子表 sibling 查询」这一入口。
