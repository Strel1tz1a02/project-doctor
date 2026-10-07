# case-14-config-regression-pool-size

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `config_regression` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制；**等待 Agent 支持**） |

设计意图：项目在**代码未做任何改动**的前提下，数据源连接池上限被回退为极小值——`application.yml` 中 `spring.datasource.hikari.maximum-pool-size: 2`。`GET /api/orders/by-user` 的查询本身很快（`orders` 已带 `idx_orders_user_created`，执行计划正常），但在并发下所有请求要竞争仅 2 条可用连接，需排队等待，P99 由约 120ms 阶跃式升高到约 800ms。

与 `slow_query` 系用例不同，本用例的缺陷**不体现在执行计划**上，也不在 Java 代码里：单条 SQL 无计划问题，真正的瓶颈是**连接池容量随并发不足导致的排队**。理想情况下可由「对照配置基线 + 放开 `maximum-pool-size` 后重测」证实（`expected.improvement` 要求放开后 `duration_ms` 至少改善 60%），但当前 Agent 的 `ProblemKind` 仅支持 `slow_query`（且 `Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`），因此**在本用例上不可能产出 `verified`**，期望结论只能是 **`lead`**，并必须显式声明限制。

用例用于在 Agent 扩展问题类型之前，先检验其是否能：

1. 识别「单条 SQL 不慢、代码没变、却随并发阶跃变慢」这一配置回归特征；
2. 给出正确的定位（配置项所在文件与行）；
3. 如实声明「无法证实为 `verified`」及原因（等待 Agent 支持新问题类型），而非勉强下结论或误报 `false_verified`。

## 目录结构

```text
case-14-config-regression-pool-size/
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
| `d1` | primary | `misconfigured_datasource_pool_size` | `src/main/resources/application.yml:11` | `lead` | 数据源连接池上限被回退为 `maximum-pool-size: 2`，并发请求需排队等待可用连接，时延随并发阶跃上升；查询走 `idx_orders_user_created`、计划正常，无缺索引 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单）
mvn spring-boot:run

# 3. 触发症状（注意本用例 load_profile 的并发度为 8）
for i in $(seq 1 8); do curl -s "http://localhost:8080/api/orders/by-user?userId=123&size=20" >/dev/null & done; wait
```

## 评估要点

- 关键观察：并发度较高时 P99 明显跃升；并发很低时小连接池不产生排队、症状不可观测（本用例 `load_profile.concurrency = 8`，为全用例组的例外值）。
- 可证实性：**无法**由单变量索引实验证实（查询已有可用索引、执行计划正常），只能以「对照配置基线 + 放开池上限后重测」佐证，故期望 `lead` 而非 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条，含「等待 Agent 支持」）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。
- **待支持标注**：当前 `ProblemKind` 不含 `config_regression`，本用例归档为「等待 Agent 支持」；待 Agent 扩展问题类型后，可重判为 `normal`（若届时能由配置对照证据闭环）。

## 与其它用例的关系

- 与 `slow_query` 系用例（`case-01`/`case-04` 等）的区别：本用例的耗时**不体现在执行计划**上，SQL 已走索引，不能用单变量索引实验证实，正是其被定为 `boundary` 的原因。
- 与 `case-13-thread-pool-no-verifiable-defect` 的区别：`case-13` 在当前代码与数据下**无**可证实缺陷（`failure / unclassified`）；本用例存在**真实且在配置层明确**的缺陷，只是在当前 Agent 能力下无法产出 `verified`，故为 `boundary / lead`。
- 与 `case-07-n-plus-one-order-user` 同属「问题类型待 Agent 支持」的预置用例，均为 `boundary / lead`；`case-14` 的缺陷位于配置层，`case-07` 位于代码调用结构层。
