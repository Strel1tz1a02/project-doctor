# case-24-slow-query-audit-log-scan-sort

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `normal`（正常用例） |
| `problem_kind` | `slow_query` |
| `difficulty` | `easy` |
| 期望结论 | `verified` |
| 来源 | 改编自 [genenetwork/genenetwork2](https://github.com/genenetwork/genenetwork2) Issue #419《Slow query》（AGPL-3.0，`source=adapted`） |

设计意图：项目**只有一个真实性能缺陷**——`audit_logs` 表除主键外无任何二级索引，按 `level` 过滤并 `ORDER BY created_at_ms DESC` 只能全表扫描 + 文件排序。该缺陷可由平台唯一允许的单变量（`variable="index"`）实验直接证实。用例考察 Agent 是否能：

1. 完成「基线 → 竞争假设 → 单变量区分实验 → 定位 → 独立验证」的闭环；
2. 为 `verified` 提供完整的结构化证据（实验引用、SQL 调用引用、代码位置、被排除的解释）；
3. 不虚构额外根因（本用例不存在干扰性次要缺陷）。

## 上游来源与原汁原味的保留

- 上游：`genenetwork/genenetwork2` Issue #419《Slow query》。
- 上游版本：`testing@a5e364f5dfd89d6a09289906da0c1fbf02c33afc`。
- 保留的原汁原味：上游为一条在大表上扫描约 2126 万行、耗时约 187 秒的原生慢查询（多列 `REGEXP`）；本用例保留其「大扫描量慢查询」的核心特征（20 万行审计日志、过滤 + 排序、`duration_ms` 退化）。
- 按数据集约定的改造：上游为多列 `REGEXP` 非 sargable 形态，无法由平台「加索引」单变量实验稳定证实；为对齐数据集 `slow_query` / `normal`（可证实）分类，将查询归一化为「按 `level` 过滤 + 按 `created_at_ms` 倒序」的可证实形态——为 `(level, created_at_ms)` 建复合索引即可由单变量实验稳定证实。技术栈统一改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；判分指标统一为可实测字段 `duration_ms`。

## 目录结构

```text
case-24-slow-query-audit-log-scan-sort/
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
| `d1` | primary | `missing_index_filter_sort` | `.../mapper/AuditLogMapper.java:14` | `verified` | `audit_logs` 除主键外无索引；`level` 过滤 + `ORDER BY created_at_ms DESC` → 全表扫描（`ALL audit_logs`）+ `Using filesort`；为 `(level, created_at_ms)` 建复合索引即可由单变量实验证实 |

期望命中根因：`d1`。期望排除的解释：`lock_contention` / `network_latency` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万审计日志）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/audit/recent?level=ERROR&limit=100"
```

## 评估要点

- 单变量实验：`baseline` 对照 `candidate_index`（为 `audit_logs(level, created_at_ms)` 建复合索引），
  重复 ≥ 3 次、相对波动 ≤ 25%、耗时差 ≥ 1ms（`MeasurementPolicy`）。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = normal_single`。
- 硬闸门（见《Agent 评估方法》正常用例）：`decision_match = exact`、
  `root_cause_recall = 1`、`code_location_hit = true`、`evidence_compliance = true`、
  `recommendation_effective = true`、`correctness_preserved = true`、`false_verified = false`。
- 若结论降级为 `lead`（`under`），用例不通过，按「漏判」单独统计。

## 与其它用例的关系

- 与 `case-15-slow-query-threads-fullscan` 同为 `slow_query` / normal，但缺陷形态不同：`case-15` 是
  「**聚合（MAX）缺索引 → 全表扫描**」，本用例是「**过滤 + 排序缺复合索引 → 全表扫描 + 文件排序**」，
  覆盖「`WHERE` 过滤叠加 `ORDER BY`」的入口。
- 与 `case-05-slow-query-skewed-status` 同走「过滤 + 排序」路径，但本用例取值分布不倾斜、收益稳定可证实，
  属可证实的 `normal` 形态。
