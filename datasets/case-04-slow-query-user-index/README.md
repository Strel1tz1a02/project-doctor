# case-04-slow-query-user-index

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `normal`（正常用例） |
| `problem_kind` | `slow_query` |
| `difficulty` | `easy` |
| 期望结论 | `verified` |

设计意图：项目**只有一个真实性能缺陷**——`orders` 表除主键外**没有任何二级索引**，按 `user_id` 过滤并排序只能全表扫描。该缺陷可由平台唯一允许的单变量（`variable="index"`）实验直接证实。用例考察 Agent 是否能：

1. 完成「基线 → 竞争假设 → 单变量区分实验 → 定位 → 独立验证」的闭环；
2. 为 `verified` 提供完整的结构化证据（实验引用、SQL 调用引用、代码位置、被排除的解释）；
3. 不虚构额外根因（本用例不存在干扰性次要缺陷）。

## 目录结构

```text
case-04-slow-query-user-index/
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
| `d1` | primary | `missing_composite_index` | `.../mapper/OrderMapper.java:17` | `verified` | `orders` 除主键外无索引；按 `user_id` 过滤 + `ORDER BY created_at DESC` → 全表扫描 + `Using filesort`；加 `(user_id, created_at)` 即可由单变量实验证实 |

期望命中根因：`d1`。期望排除的解释：`lock_contention` / `network_latency` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/orders/by-user?userId=123&size=20"
```

## 评估要点

- 单变量实验：`baseline` 对照 `candidate_index`（为 `orders` 加 `(user_id, created_at)` 复合索引），
  重复 ≥ 3 次、相对波动 ≤ 25%、耗时差 ≥ 1ms（`MeasurementPolicy`）。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = normal_single`。
- 硬闸门（见《Agent 评估方法》正常用例）：`decision_match = exact`、
  `root_cause_recall = 1`、`code_location_hit = true`、`evidence_compliance = true`、
  `recommendation_effective = true`、`correctness_preserved = true`、`false_verified = false`。
- 若结论降级为 `lead`（`under`），用例不通过，按「漏判」单独统计。

## 与其它用例的关系

- 与 `case-01-slow-query-fullscan` 同为 normal 用例，但缺陷形态不同：`case-01` 是
  「有 `idx_orders_user_id`，缺 `(status, created_at)`」，本用例是「**除主键外无任何索引**」；
  两者共同覆盖「索引缺失 → 全表扫描」的两种常见入口（过滤字段不同、是否已有其它索引不同）。
- 与 `case-06-slow-query-undersized` 构成对照：本用例数据充足、缺陷可证实；`case-06` 保留同类
  缺陷但数据规模过小、无法证实，用于检验 Agent 是否会对「真实但不可证实」的缺陷强行下结论。
