# case-30-slow-query-date-function-column

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `slow_query` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自「对时间列按天使用函数过滤导致索引失效」的典型慢查询场景（`source=adapted`，许可证待核验） |

设计意图：项目存在**真实缺陷**——查询以 `DATE(FROM_UNIXTIME(occurred_at_ms / 1000)) = #{day}` 对时间列做函数包裹后过滤，谓词**非 sargable**，即使为 `occurred_at_ms` 建立普通 B-tree 索引也无法参与该过滤，仍只能全表扫描 + 文件排序。因此平台唯一允许的单变量（`variable="index"`）实验无法带来稳定收益，无法跨过可证实阈值，期望整体 `decision=lead`。用例考察 Agent 是否能：

1. 判定「缺陷真实，但常规加索引修复无效」，从而**不下 `verified` 结论**（避免 `false_verified`）；
2. 指出正确的修复方向（把按天过滤改写为 `occurred_at_ms` 的毫秒半开区间 `[startMs, endMs)`，使谓词可 sargable），而非简单建索引；
3. 显式声明收益不确定所依赖的条件（函数包裹、数据分布、单日命中率）。

## 上游来源与原汁原味的保留

- 上游：常见的「审计/日志/订单按天（或按月）查询」实现，过滤条件对时间列使用 `DATE()` / `FROM_UNIXTIME()` / `YEAR()` 等函数，使时间列上的索引失效、退化为全表扫描。
- 保留的原汁原味：过滤谓词对索引列施加函数导致**非 sargable**、无法利用该列索引这一核心特征。
- 按数据集约定的改造：技术栈统一为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；判分指标统一为可实测字段 `duration_ms`；时间以毫秒 `BIGINT` 存储并用 `FROM_UNIXTIME(occurred_at_ms / 1000)` 还原，贴近真实实现；为对齐数据集 `slow_query` / boundary 分类，保留「加普通索引收益不确定」的边界性质。上游许可证尚未核验，`provenance.license` 标注为「待核验」，不臆断。

## 目录结构

```text
case-30-slow-query-date-function-column/
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
| `d1` | primary | `function_wrapped_index_column` | `.../mapper/AuditEventMapper.java:16` | `lead` | `DATE(FROM_UNIXTIME(occurred_at_ms / 1000)) = #{day}` 对时间列施加函数，谓词非 sargable，`occurred_at_ms` 上的 B-tree 索引无法参与过滤，只能全表扫描；单变量加索引实验收益不确定 |
| `d2` | secondary | `missing_index_sort_column` | `.../mapper/AuditEventMapper.java:17` | `lead` | `ORDER BY occurred_at_ms DESC` 无对应索引，需 `Using filesort`，耗时贡献未在单变量实验下单独隔离 |
| `d3` | decoy | `select_star` | `.../mapper/AuditEventMapper.java:14` | `unclassified` | `SELECT *` 返回全部列，无法利用覆盖索引，非本用例耗时根因 |

期望命中根因：`d1`。期望排除的解释：`lock_contention` / `network_latency` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 30 万条审计事件）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/audit/events/by-day?day=2025-06-10&size=20"
```

## 评估要点

- `decision_match = under`（期望 `lead`，Agent 不得给出 `verified`）。
- `false_verified = false`：Agent 若因「加了索引」就宣称 `verified` 即判失败。
- `limitation_declared`：须命中 `case.json` 中 `expected.limitations_required` 的 3 条限制声明。
- `reward_profile = boundary_composite`，`timeout_seconds = 2400`。
- 单变量实验 `variable="index"`（为 `occurred_at_ms` 建普通 B-tree 索引）在重复 ≥ 3 次下**无法**稳定达到 `expected.improvement.min_improvement_percent`，故整体期望 `lead`。

## 与其它用例的关系

- 与 `case-25-slow-query-leading-wildcard` 同为 `slow_query` / boundary / `lead`，且同属「谓词非 sargable、常规索引修复无效」家族，但边界成因不同：`case-25` 是前导通配符 `LIKE '%kw%'` 作用于文本列，本用例是**函数包裹时间列**（`DATE(FROM_UNIXTIME(...))`），且正确修复是改写为毫秒半开区间的范围谓词。
- 与 `case-24-slow-query-audit-log-scan-sort`（过滤 + 排序缺复合索引，`normal`/`verified`）形成对照：同走「过滤 + 排序」路径，`case-24` 加复合索引即可稳定证实，本用例因函数包裹导致无法证实。
