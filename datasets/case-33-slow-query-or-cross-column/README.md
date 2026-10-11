# case-33-slow-query-or-cross-column

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `slow_query` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自 MySQL 优化器「跨列 OR 一侧无索引 → 放弃 index_merge → 全表扫描」的公开行为与缺陷报告（`source=adapted`，许可证待核验） |

设计意图：项目**只有一个真实性能缺陷**——`orders` 表只在 `user_id` 上建单列索引，查询 `user_id = ? OR status = ?` 是跨列 OR，由于 `status` 无可用索引，优化器无法用 `index_merge` 合并两侧索引，退化为全表扫描并伴随文件排序。该缺陷可定位、可用 EXPLAIN 取证，但属非 sargable 谓词形态，无法由平台唯一允许的单变量（`variable="index"`）实验稳定证实。用例考察 Agent 是否能：

1. 借助 EXPLAIN（`type=ALL` / `key=NULL` / `Using filesort`）判定「索引存在但被谓词形态弃用」；
2. 区分「缺索引」与「索引因谓词形态失效」两类不同根因；
3. 显式声明边界限制（非 sargable、结论依赖优化器）。

## 上游来源与原汁原味的保留

- 上游：MySQL 优化器在处理跨列 OR 时的索引选择行为（公开缺陷报告 MySQL Bug #119867 及同类报告；公开内核文档）。
- 保留的原汁原味：跨列 OR 谓词、其中一侧无可用索引、优化器放弃索引合并 → 全表扫描，这是数据库内核实测可复现的原生行为。
- 按数据集约定的改造：技术栈统一为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；判分指标统一为可实测字段 `duration_ms`；数据规模收敛到 30 万订单以保证可复现与观测窗口可控。

## 目录结构

```text
case-33-slow-query-or-cross-column/
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
| `d1` | primary | `or_across_columns_index_drop` | `.../mapper/OrderMapper.java:14` | `lead` | `orders(user_id)` 有索引但 `status` 无索引；`user_id = ? OR status = ?` 跨列 OR → 优化器放弃 `index_merge` → `ALL orders` + `Using filesort` |

期望命中根因：`d1`。期望排除的解释：`lock_contention` / `network_latency` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 30 万订单）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/orders/search?userId=1000&status=PAID&limit=50"
```

## 评估要点

- 单变量实验：`baseline` 对照 `candidate_index`（补 `status` 索引以启用 `index_merge`），
  重复 ≥ 3 次、相对波动 ≤ 25%、耗时差 ≥ 1ms（`MeasurementPolicy`）。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界用例考察「显式声明限制」：Agent 须说明该形态为非 sargable 谓词、结论依赖优化器，并给出 EXPLAIN 证据。
- 若 Agent 强行给出 `verified`，`false_verified = false` 不通过。

## 与其它用例的关系

- 与 `case-25-slow-query-leading-wildcard` 同属「非 sargable 谓词导致索引失效」，但机制不同：`case-25` 是前导通配符，本用例是**跨列 OR 且一侧无索引使 `index_merge` 不可用**。
- 与 `case-30-slow-query-function-wrapped-index` 的「函数包裹索引列」不同：本用例索引列未被包裹，失效来自优化器的 OR 处理策略。
