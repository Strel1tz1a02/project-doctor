# case-05-slow-query-skewed-status

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `slow_query` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制） |

设计意图：项目存在**一个真实缺陷**——`orders` 表只有 `idx_orders_user_id`，按 `status` 过滤并 `ORDER BY created_at DESC` **缺少 `(status, created_at)` 复合索引**。但与 `case-01`/`case-02` 不同，本用例的 `status` 取值**高度倾斜**（`PAID` ≈ 80%，`CREATED`/`SHIPPED` 各 ≈ 10%），导致单变量索引实验的**收益随被查询取值而变**：

- 查询低占比取值（如 `SHIPPED`）时，复合索引可显著加速，接近可证实；
- 查询高占比取值（如 `PAID`）时，优化器可能判定走全表扫描更划算，加索引后**耗时几乎不变**，无法稳定跨过可证实阈值。

因此本用例的期望结论是 **`lead`**（定位到 d1 但收益不可稳定证实），且 Agent **必须显式声明限制**，不得强行给出 `verified`。用例考察 Agent 是否能：

1. 识别「缺陷真实存在」与「收益可否证实」之间的区别；
2. 在收益依赖数据分布时，选择 `lead` 而非过度下结论（`false_verified`）；
3. 完整声明不确定性来源（取值依赖、次要缺陷未隔离、分布/规模前提）。

## 目录结构

```text
case-05-slow-query-skewed-status/
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
| `d1` | primary | `missing_composite_index` | `.../mapper/OrderMapper.java:19` | `lead` | `orders` 仅有 `idx_orders_user_id`；`status` 过滤 + `ORDER BY created_at DESC` → 全表扫描 + `Using filesort`；加 `(status, created_at)` 可改善，但倾斜分布下收益依赖取值，不可稳定证实 |
| `d2` | secondary | `redundant_count` | `.../mapper/OrderMapper.java:23` | `lead` | `recentByStatus` 先执行一次同状态 `COUNT(*)`，耗时贡献未在单变量实验下隔离 |
| `d3` | decoy | `select_star` | `.../mapper/OrderMapper.java:14` | `unclassified` | `SELECT *` 使覆盖索引失效，但非本用例耗时根因（干扰项） |

期望命中根因：`d1`。期望排除的解释：`lock_contention` / `network_latency` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单，状态按权重倾斜）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/orders/by-status?status=PAID&size=20"
curl "http://localhost:8080/api/orders/by-status?status=SHIPPED&size=20"
```

## 评估要点

- 单变量实验：`baseline` 对照 `candidate_index`（为 `orders` 加 `(status, created_at)` 复合索引），
  重复 ≥ 3 次、相对波动 ≤ 25%、耗时差 ≥ 1ms（`MeasurementPolicy`）。
- 关键观察：同一实验在 `status=PAID` 与 `status=SHIPPED` 下收益差异明显，收益不稳定。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。

## 与其它用例的关系

- 与 `case-01-slow-query-fullscan`、`case-02-slow-query-composite` 同走 status 过滤路径的缺索引形态，
  但通过**数据分布倾斜**引入「收益不可稳定证实」的边界，区别于 `case-01`（可证实）与
  `case-02`（组合缺陷，主缺陷仍可证实）。
- 与 `case-06-slow-query-undersized` 共同覆盖「缺陷真实但不可/难以证实」的两种边界/失败入口：
  本用例因**分布倾斜**导致收益波动，`case-06` 因**数据规模过小**导致完全不可证实。
