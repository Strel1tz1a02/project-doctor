# case-38-n-plus-one-repository-nested-commits

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `n_plus_one` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自常见的「仓库列表 → 提交明细 → 提交者」逐层回查 N+1 场景（`source=adapted`，许可证待核验） |

设计意图：仓库列表接口在拿到最近仓库列表后，**在外层循环中对每个仓库逐条查询其提交列表**，并**在内层循环中对每条提交逐条回查提交者名称**，形成嵌套的 `1+N+N×M` 次数据库往返。单条查询走主键 / 索引、执行计划本身无问题，缺陷在于**调用次数随仓库数线性增长、并按每仓库提交数进一步放大**。用例考察 Agent 是否能：

1. 把根因定位到「循环中的逐条回查」（N+1 / 嵌套 N+1），而非任何单条 SQL 的执行计划；
2. 认识到 `n_plus_one` 现虽由 Agent 的 `ProblemKind` 支持，但本用例未纳入「逐条 vs 批量」判别实验与批量改造后复测增益等结构化证据，故维持 `lead`；
3. 不虚构不存在的索引类根因（避免 `false_verified`）。

## 上游来源与原汁原味的保留

- 上游：常见的「仓库 / 项目列表 → 提交明细 → 提交者」逐层回查实现（许可证待核验，不臆断具体仓库与提交）。
- 保留的原汁原味：列表查询返回 N 条记录后，在外层循环逐条查询关联子列表，再在内层循环逐条查询子列表的关联实体，使数据库往返随 N 与 M 放大。
- 按数据集约定的改造：技术栈统一为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；把提交维度规整为 `commits` 表、提交者维度规整为 `committers` 小表，形成外层仓库→提交列表（N）+ 内层提交→提交者（N×M）的嵌套循环（`1+N+N×M`）。上游许可证尚未核验，`provenance.license` 标注为「待核验」。

## 目录结构

```text
case-38-n-plus-one-repository-nested-commits/
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
| `d1` | primary | `n_plus_one` | `.../service/RepositoryService.java:29` | `lead` | `buildRepositories` 先取最近仓库（1 次）再在外层循环逐条 `findCommitsByRepositoryId`（N 次）；单条走 `idx_commits_repository_id`，问题在于调用次数 |
| `d2` | secondary | `n_plus_one` | `.../service/RepositoryService.java:35` | `lead` | 内层循环逐条 `findCommitterNameById`，形成嵌套放大（N×M），与 d1 同源，合计 `1+N+N×M`；primary 仍定位在外层仓库→提交列表查询 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 2 万仓库 / 20 万提交 / 5 万提交者）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/repositories/recent?size=20"
```

## 评估要点

- `decision_match = exact`（期望 `lead`，Agent 不得给出 `verified`）。
- `root_cause_recall`：命中 `d1` 即视为召回主根因；`d2` 属同源次要。
- `false_verified = false`：Agent 若宣称 `verified`（例如声称「已加索引证实」）即判失败。
- `limitation_declared`：须命中 `case.json` 中 `expected.limitations_required` 的 3 条声明（判定依据、`n_plus_one` 已支持但证据不足维持 `lead`、依赖列表页大小）。
- `reward_profile = boundary_composite`，`timeout_seconds = 2400`。
- 该缺陷**不能**由平台单变量索引实验证实；本用例亦未纳入「逐条 vs 批量」判别实验与改造复测增益证据，故整体期望 `lead`。

## 与其它用例的关系

- 与 `case-27-n-plus-one-job-steps-logs` 区分：`case-27` 是「任务逐 job 查询步骤与日志」（两个并列子循环）；本用例是「仓库 → 提交 → 提交者」的两层**嵌套**循环，放大维度为 N×M。
- 与 `case-07` / `case-16` / `case-26` / `case-31` / `case-36` / `case-37` 同为 `n_plus_one` / boundary / `lead`，但入口不同：本用例覆盖「代码仓库提交汇总的嵌套逐条回查」。
