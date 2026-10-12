# case-28-connection-pool-nested-acquire

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `connection_pool` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自 [open-webui/open-webui](https://github.com/open-webui/open-webui)（MIT，`source=adapted`） |

设计意图：聚合接口**在持有外层连接的 `try-with-resources` 作用域内**进入 for 循环，循环内每次调用都**重新向连接池申请连接**（嵌套取连接）。池上限为 4，并发请求数达到池上限时外层连接占满全部连接，循环内的嵌套取连接全部阻塞直至 `connection-timeout`。用例考察 Agent 是否能：

1. 识别「冷启动单请求正常、并发升高才恶化」的资源占用特征，并把它归因到**连接持有范围与取连接时机相互嵌套**，而非慢 SQL、缺索引或 N+1；
2. 在问题类型尚未被 Agent 支持时给出 `lead` 结论并**显式声明限制**（不得伪造 `verified`）；
3. 不把连接池上限这类环境参数、也不把循环内逐条 COUNT 误判为根因（逐条 COUNT 均可走索引）。

## 上游来源与原汁原味的保留

- 上游：`open-webui/open-webui`（许可证 MIT，已确认）。
- 保留的原汁原味：聚合接口在处理遥测指标时，于**持有连接的作用域内**对每个维度逐条发起低效 COUNT 查询，频繁申请连接，并在并发下把连接池占满、触发获取连接超时。
- 按数据集约定的改造：上游为 Python，本项目按统一骨架改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；维度由业务维度规整为 `model-01..model-16`；判分指标统一为可实测字段 `duration_ms`；连接池上限收敛为 4，使并发下的饥饿在秒级稳定复现。

## 目录结构

```text
case-28-connection-pool-nested-acquire/
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
| `d1` | primary | `nested_connection_acquire` | `src/main/java/com/example/slowquery/service/MetricsAggregateService.java:28` | `lead` | `aggregate` 方法一开始即 `dataSource.getConnection()` 取得外层连接，并在其作用域内的 for 循环中调用 `metricsMapper.countByModel` 嵌套取连接；并发达到池上限 4 时嵌套取连接全部阻塞至超时 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `jvm_gc_pause`。

> 说明：
> - `application.yml` 中的 `hikari.maximum-pool-size: 4` 与 `connection-timeout: 3000` 是**环境参数**，用于让占用可观测，**不是**缺陷本身；主根因在 `MetricsAggregateService.aggregate` 的连接持有范围与嵌套取连接。
> - 循环内的逐模型 `countByModel` 是**可走 `idx_telemetry_model` 的单条查询**，故 `missing_index` / `slow_query` 不是根因；其问题在「取连接时机」而非「SQL 本身」。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万条 telemetry_events）
mvn spring-boot:run

# 3. 触发症状（并发请求，使外层连接占满池上限 4，嵌套取连接阻塞）
curl "http://localhost:8080/api/metrics/aggregate?models=16"
```

## 评估要点

- 边界用例（问题类型 `connection_pool`，等待 Agent 支持）：**不可由单变量索引实验证实**；且当前 Agent 的 `ProblemKind` 仅支持 `slow_query` / `n_plus_one` / `deep_pagination`、`Finding.verified_requires_structural_evidence` 要求 `kind ∈ {slow_query, n_plus_one, deep_pagination}`，故在本用例上不可能产出 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- `decision_match`：期望 `lead`（Agent 若给出 `verified` 即触发 `false_verified` 硬闸门）。
- `limitation_declared`：必须声明三条 `expected.limitations_required`（并发窗口依赖、问题类型未支持、量化需连接池指标且逐条 COUNT 走索引）。
- `false_verified` 硬闸门：任何为连接池问题伪造 `verified` 的输出直接判负。
- **待支持标注**：等待 Agent 支持 `connection_pool` 问题类型。

## 与其它用例的关系

- 与 `case-17`（`connection_pool` / `connection_hold`）区分：`case-17` 是在**轮询等待期间**持有连接（持有范围跨越 sleep），循环内不再取连接；本用例是**在外层连接作用域内嵌套取连接**（持有与取连接相互嵌套），机制不同。
- 与 `case-09`（`connection_pool` / `connection_leak`）区分：`case-09` 是正常路径下从不归还、跨调用累积；本用例连接会归还，仅因嵌套取连接在并发下瞬时占满。
- 与 `case-16` / `case-26` / `case-27`（`n_plus_one`）区分：本用例循环内逐条 COUNT 均可走索引，问题不在往返次数，而在取连接时机，故在 `expected.excluded_explanations` 中排除 `n_plus_one`。
