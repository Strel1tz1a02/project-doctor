# case-07-n-plus-one-order-user

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `n_plus_one` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制；**等待 Agent 支持**） |

设计意图：项目存在**一个真实、机制明确的结构性缺陷**——`GET /api/orders/recent` 先用一次查询取回 `size` 条订单，再在 `for` 循环中**逐条**调用 `findUserById` 回填下单用户信息，形成 `1 + size` 次数据库往返（经典 N+1）。

与 `slow_query` 系用例不同，本用例的缺陷**不是靠执行计划**体现的：单条 `findUserById` 走主键、计划毫无问题，真正的开销是**数据库往返次数随列表条数线性增长**。理想情况下可由「统计一次请求的 SQL 调用次数」证实，但当前 Agent 的 `ProblemKind` 仅支持 `slow_query`（且 `Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`），因此**在本用例上不可能产出 `verified`**，期望结论只能是 **`lead`**，并必须显式声明限制。

用例用于在 Agent 扩展问题类型之前，先检验其是否能：

1. 识别「单条查询不慢、整体却随数据量增长」这一 N+1 特征；
2. 给出正确的定位（逐条查询的调用点）；
3. 如实声明「无法证实为 `verified`」及原因（等待 Agent 支持新问题类型），而非勉强下结论或误报 `false_verified`。

## 目录结构

```text
case-07-n-plus-one-order-user/
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
| `d1` | primary | `n_plus_one` | `.../service/OrderService.java:33` | `lead` | `recentOrdersWithUser` 在 for 循环中对每条订单单独调用 `findUserById`，形成 `1+size` 次往返；单条 SQL 走主键无问题，开销来自调用次数 |
| `d2` | decoy | `select_star` | `.../mapper/OrderMapper.java:15` | `unclassified` | 列表查询用 `SELECT *`（带出 `remark`），覆盖索引失效；但列表查询走 `idx_orders_created_at`，非本用例根因（干扰项） |

期望命中根因：`d1`。期望排除的解释：`lock_contention` / `network_latency` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 5 万用户 + 20 万订单）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/orders/recent?size=200"
```

## 评估要点

- 关键观察：请求耗时随 `size` 增大而近似线性增长；`size` 很小时不可观测。
- 可证实性：**无法**由单变量索引实验证实（单条 SQL 无计划问题）；只能以调用次数增长佐证，故期望 `lead` 而非 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条，含「等待 Agent 支持」）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。
- **待支持标注**：当前 `ProblemKind` 不含 `n_plus_one`，本用例归档为「等待 Agent 支持」；待 Agent 扩展问题类型后，可重判为 `normal`（若届时能由调用次数证据闭环）。

## 与其它用例的关系

- 与 `case-02-slow-query-composite` 的 N+1 分量互补：`case-02` 把 N+1 作为**组合缺陷中的次要项**用于观察 Agent 是否会遗漏；本用例把 N+1 作为**唯一 primary** 独立成卡。
- 与 `case-08-deep-pagination-large-offset` 同属「问题类型待 Agent 支持」的预置用例，均为 `boundary / lead`。
- 与 `slow_query` 系用例的区别：本用例的耗时**不体现在执行计划**上，不能用单变量索引实验证实，正是其被定为 `boundary` 的原因。
