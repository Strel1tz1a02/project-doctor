# case-15-slow-query-threads-fullscan

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `normal`（正常用例） |
| `problem_kind` | `slow_query` |
| `difficulty` | `easy` |
| 期望结论 | `verified` |
| 来源 | 改编自 [openai/codex](https://github.com/openai/codex) Issue #38373（Apache-2.0，`source=adapted`） |

设计意图：项目**只有一个真实性能缺陷**——`threads` 表在 `updated_at_ms` / `recency_at_ms` 上没有索引，`SELECT MAX(...)` 聚合只能全表扫描。该缺陷可由平台唯一允许的单变量（`variable="index"`）实验直接证实。用例考察 Agent 是否能：

1. 完成「基线 → 竞争假设 → 单变量区分实验 → 定位 → 独立验证」的闭环；
2. 为 `verified` 提供完整的结构化证据（实验引用、SQL 调用引用、代码位置、被排除的解释）；
3. 不虚构额外根因（本用例不存在干扰性次要缺陷）。

## 上游来源与原汁原味的保留

- 上游：`openai/codex` Issue #38373《State startup query scans the full threads table》。
- 问题存在时 commit：`a7b8c074b577f897111c14de3a5e127b91e2a479`（issue 正文指出该查询在此 commit 仍存在）；仓库默认分支核验值 `main@806d9732c974bc8a51b8317c1bd8985544fe627c`。
- 保留的原汁原味：原查询 `SELECT MAX(threads.updated_at_ms), MAX(threads.recency_at_ms) FROM threads`（执行计划 `SCAN threads`）被逐字迁移到 `ThreadMapper.selectMaxTimestamps()`；表名 `threads`、列名 `updated_at_ms` / `recency_at_ms` 保持不变。
- 按数据集约定的改造：上游为 Rust + SQLx，本项目按统一骨架改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；判分指标由上游的「启动查询耗时」统一为可实测字段 `duration_ms`；数据规模由上游 2.3 万线程放大到 20 万行以保证全表扫描与走索引取 MAX 的差异稳定可测。

## 目录结构

```text
case-15-slow-query-threads-fullscan/
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
| `d1` | primary | `missing_index_max_scan` | `.../mapper/ThreadMapper.java:11` | `verified` | `threads` 除主键外无索引；`SELECT MAX(updated_at_ms), MAX(recency_at_ms)` → 全表扫描（`SCAN threads`）；为两列加索引即可由单变量实验证实 |

期望命中根因：`d1`。期望排除的解释：`lock_contention` / `network_latency` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万线程）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/threads/max-timestamps"
```

## 评估要点

- 单变量实验：`baseline` 对照 `candidate_index`（为 `threads(updated_at_ms)` / `threads(recency_at_ms)` 建索引），
  重复 ≥ 3 次、相对波动 ≤ 25%、耗时差 ≥ 1ms（`MeasurementPolicy`）。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = normal_single`。
- 硬闸门（见《Agent 评估方法》正常用例）：`decision_match = exact`、
  `root_cause_recall = 1`、`code_location_hit = true`、`evidence_compliance = true`、
  `recommendation_effective = true`、`correctness_preserved = true`、`false_verified = false`。
- 若结论降级为 `lead`（`under`），用例不通过，按「漏判」单独统计。

## 与其它用例的关系

- 与 `case-01` / `case-04` 同为 `slow_query` / normal，但缺陷形态不同：前者是「过滤字段缺索引」，
  本用例是「**聚合（MAX）缺索引 → 全表扫描**」，覆盖「无 WHERE 过滤、仅聚合取边界值」的入口。
- `case-04` 从 case-04 骨架复制改造而来，二者共享统一骨架，便于对照。
