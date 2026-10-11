# case-16-n-plus-one-stop-times-hotpath

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `n_plus_one` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自 [OneBusAway/maglev](https://github.com/OneBusAway/maglev) Issue #404（Apache-2.0，`source=adapted`） |

设计意图：`GET /api/trips/block-details` 需要为最近行程列表附带每个行程的停靠点数量。项目在**热路径循环内逐条查询 StopTimes**（N+1）：先用一次查询取回 size 条行程，再在 `for` 循环中为每个 trip 单独查询 `stop_times`，形成 1+size 次数据库往返。用例考察 Agent 是否能：

1. 识别「代码结构导致的查询次数放大」——耗时随列表条数线性增长，而非任何单条 SQL 的执行计划问题；
2. 在问题类型尚未被 Agent 支持时，给出 `lead` 结论并**显式声明限制**（不得为了拿分伪造 `verified`）；
3. 不把同源但非 primary 的相邻热路径（d2）或索引问题误判为「缺索引慢查询」根因。

## 上游来源与原汁原味的保留

- 上游：`OneBusAway/maglev` Issue #404《Performance Bug: N+1 Query Problem - StopTimes Queries in Hot Path Loops》。
- 固定版本：commit `main@601597759171a7b7df98799d13687870d910f4f8`（核验当日 HEAD）；许可证 Apache-2.0。
- 保留的原汁原味：
  - 上游精确代码位置 `internal/restapi/trips_helper.go`：`GetNextAndPreviousTripIDs`（line 199，循环 line 198）、`calculateBlockTripSequence`（line 479，循环 line 471）——均在循环内对每个 trip 单独查询 StopTimes；
  - 逐 trip 查询语义 `WHERE trip_id = ?`，迁移为本项目 `TripMapper.findStopTimesByTripId(@Param("tripId") String tripId)`；
  - GTFS 表名 `trips` / `stop_times` / `stops` 与列名 `trip_id` / `block_id` / `stop_sequence` / `stop_id` / `arrival_time` / `departure_time` 保持不变；
  - 批量解 `gtfsdb/query.sql` line 965 `GetStopTimesForTripIDs`（上游已在 `trips_for_location_handler.go` line 233 使用）映射为本用例建议的批量修复方向。
- 按数据集约定的改造：上游为 Go + gtfsdb，本项目按统一骨架改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；判分指标统一为可实测字段 `duration_ms`；数据规模按数据集约定设定为 stops=5000、trips=50000、stop_times=500000（每 trip 10 条），以保证 N+1 与批量查询的差异稳定可测。

## 目录结构

```text
case-16-n-plus-one-stop-times-hotpath/
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
| `d1` | primary | `n_plus_one` | `src/main/java/com/example/slowquery/service/BlockTripService.java:35` | `lead` | `getNextAndPreviousTripIds` 在 `for` 循环内逐 trip 调用 `findStopTimesByTripId`，形成 1+size 次往返；单条按主键查询执行计划无问题 |
| `d2` | secondary | `n_plus_one` | `src/main/java/com/example/slowquery/service/BlockTripService.java:51` | `lead` | `calculateBlockTripSequence` 第二个循环内再次逐 trip 查询，与 d1 同源、有贡献但非唯一主根因 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 stops=5000 / trips=50000 / stop_times=500000）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/trips/block-details?size=200"
```

## 评估要点

- 边界用例（问题类型 `n_plus_one`，等待 Agent 支持）：本用例**不可由单变量实验证实**——单条 `findStopTimesByTripId` 按主键 `(trip_id, stop_sequence)` 走索引、执行计划无问题，耗时来自调用次数随 `size` 线性增长；且当前 Agent 的 `ProblemKind` 仅支持 `slow_query`、`Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`，故在本用例上不可能产出 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- `decision_match`：期望 `lead`（Agent 若给出 `verified` 即触发 `false_verified` 硬闸门）。
- `limitation_declared`：必须声明三条 `expected.limitations_required`（判定依据、问题类型未支持、依赖 `size`）。
- `false_verified` 硬闸门：任何为 N+1 伪造 `verified` 的输出直接判负。
- **待支持标注**：等待 Agent 支持 `n_plus_one` 问题类型；届时本用例可升级为 `normal`。

## 与其它用例的关系

- 与 `case-07` / `case-17` 同属「热路径循环内逐条查询」家族：`case-07` 为「订单 → 用户」N+1，本用例为「行程 → 停靠点序列（StopTimes）」N+1。
- 与 `case-15` / `case-04` 对照：后两者是 `slow_query`（缺索引 → 全表扫描）、`decision=verified`；本用例是 `n_plus_one`、`decision=lead`，用于区分「执行计划问题」与「查询次数放大问题」。
- 与 `case-14` 一致，本用例显式提供 `secondary`（d2）以检验 Agent 是否能把主根因收敛到唯一 `primary`。
