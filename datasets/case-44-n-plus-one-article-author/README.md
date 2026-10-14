# case-44-n-plus-one-article-author

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `n_plus_one` |
| `difficulty` | `medium` |
| 期望结论 | `verified`（Agent 已支持 `n_plus_one`） |
| 首批角色 | **应修 N+1**（诊断 + 修正一体化首批三类之一） |

设计意图：项目存在**一个真实、机制明确的结构性缺陷**——`GET /api/articles/recent` 先用一次查询取回 `size` 篇文章，再在 `for` 循环中**逐条**调用 `findAuthorById` 回填作者信息，形成 `1 + size` 次数据库往返（经典 N+1）。

与 `slow_query` 系用例不同，本用例的缺陷**不是靠执行计划**体现的：单条 `findAuthorById` 走主键、计划毫无问题，真正的开销是**数据库往返次数随列表条数线性增长**。Agent 的 `ProblemKind` 现已支持 `n_plus_one`，可由「统计一次请求的 SQL 调用次数」这类结构化证据证实，因此**本用例期望整体结论为 `verified`**。

本用例是**首批「一体化评估」三类用例中的「应修 N+1」**，用于检验两 Agent 能否真实接力：

1. **诊断 Agent**：识别「单条查询不慢、整体却随数据量增长」的 N+1 特征，给出正确的定位（逐条查询的调用点），以「随列表条数线性增长的额外数据库往返次数」为结构化证据得出 `verified`，并把 Finding **本轮真实生成并持久化**；
2. **修正 Agent**：在**独立会话**中读取同一 Finding，把批量查询改造落在期望缺陷位置；
3. **平台隔离执行**：构建通过（`build_result != failed`）后执行补丁，由诊断层独立复测。

## 目录结构

```text
case-44-n-plus-one-article-author/
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
| `d1` | primary | `n_plus_one` | `.../service/ArticleService.java:32` | `verified` | `recentArticlesWithAuthor` 在 for 循环中对每篇文章单独调用 `findAuthorById`，形成 `1+size` 次往返；单条 SQL 走主键无问题，开销来自调用次数 |
| `d2` | decoy | `select_star` | `.../mapper/ArticleMapper.java:15` | `unclassified` | 列表查询用 `SELECT *`（带出 `summary`）；但列表查询走 `idx_articles_created_at`，非本用例根因（干扰项） |

期望命中根因：`d1`。期望排除的解释：`lock_contention` / `network_latency` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 5 万作者 + 20 万文章）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/articles/recent?size=200"
```

## 评估要点

- 关键观察：请求耗时随 `size` 增大而近似线性增长；`size` 很小时不可观测。
- 可证实性：**不能**由单变量索引实验证实（单条 SQL 无计划问题），但可由「随列表条数线性增长的额外数据库往返次数」这一结构化证据闭环，故期望 `verified`。
- 接口声明了三块期望，评分器据此从运行包取值：
  - `expected.repair = {"expected_to_change": true, "target_defect_ids": ["d1"]}` → 评估 4 项 `repair_*`；
  - `expected.handoff = {}` → 评估 1 项 `handoff_valid`（交接链）；
  - `expected.decision = verified` → 并入 `_normal_gates` 硬闸门。
- 交接链判定（`handoff_valid`）：`task_id` / `finding_id` / `repair_id` / `source_commit` 四 ID 齐备 **且** `finding_from_this_run = true`（不得预置 Finding 冒充诊断产物）**且** 修正会话独立（`repair_session_id` 非空且 ≠ `diagnosis_session_id`）。缺 `handoff` 块即 `valid = false`，与「链路不完整」同样计为不通过。
- 构建失败不计成功：`handoff.build_result == "failed"` 时 `build_ok = false`，`repair_warranted` / `gain_attributable` 一律不成立。
- 边界判定：期望 `decision_match = exact`（`verified`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 2 条：判定依据来自往返次数而非执行计划、结论依赖 `size`）。
- 虽登记为 `boundary`，但 `expected.decision == verified` 时评分器会将 `_normal_gates` 并入硬闸门（`metrics.py` `_build_gates`），故对结论层的要求与 `normal` 用例一致。
- 若 Agent 在证据不足时（例如未观测到往返次数放大）仍给出 `verified`，将触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。

## 与其它用例的关系

- 与 `case-07-n-plus-one-order-user` 同构（订单-用户 → 文章-作者），但**本用例额外声明 `expected.handoff`**，是首批「诊断 → 修正一体化」交接链的**正向样板**（应修、应改对位置）。
- 与 `case-16-n-plus-one-stop-times-hotpath`（**证据不足停**）、`case-46-n-plus-one-out-of-bounds-stop`（**越界停**）构成首批 N+1 三类。
- 与 `case-02-slow-query-composite` 的 N+1 分量互补：`case-02` 把 N+1 作为**组合缺陷中的次要项**用于观察 Agent 是否会遗漏；本用例把 N+1 作为**唯一 primary** 独立成卡。
