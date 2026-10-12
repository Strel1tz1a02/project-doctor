# case-39-connection-pool-cursor-stream-hold

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `connection_pool` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自常见的「报表导出在事务内用 ORM 游标/流式读取大结果集并逐行加工」场景（`source=adapted`，上游许可证待核验） |

设计意图：报表导出方法被标注 `@Transactional`，方法体内用 MyBatis `Cursor` 流式读取一批数据，并在 `try-with-resources` 的**整个遍历过程中逐行做较重的字段加工**。由于 MyBatis 游标必须与绑定的 SqlSession/连接保持打开，而外层事务又覆盖了整个方法，**数据库连接在流式遍历全过程被占用**。池上限为 4，并发请求数达到池上限时全部连接都被这类长流式请求占用，其余请求在获取连接处阻塞直至 `connection-timeout(3000ms)` 并失败；冷启动单请求可正常返回，仅并发升高时恶化。用例考察 Agent 是否能：

1. 识别「冷启动单请求正常、并发升高才恶化」的资源占用特征，并把它归因到**流式游标遍历期间连接被事务长期占用**，而非慢 SQL、缺索引或 N+1；
2. 在问题类型尚未被 Agent 支持时给出 `lead` 结论并**显式声明限制**（不得伪造 `verified`）；
3. 不把连接池上限、逐行加工耗时这类环境/实现参数误判为根因（`streamRows` 单条查询可走 `idx_report_region_id`）。

## 上游来源与原汁原味的保留

- 上游：常见的「报表/导出服务在数据库事务内使用游标（cursor）流式读取大结果集，逐行处理」工程模式（许可证待核验，不臆断具体仓库/提交）。
- 保留的原汁原味：处理流程为「开事务 → 游标流式读取 → 在事务边界内逐行加工 → 方法返回时提交」，连接持有时长等于整段流式遍历时长。
- 按数据集约定的改造：统一改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0 骨架；逐行加工以固定规模的 CPU 计算模拟；判分指标统一为可实测字段 `duration_ms`；连接池上限收敛为 4，使并发下的饥饿在秒级稳定复现。

## 目录结构

```text
case-39-connection-pool-cursor-stream-hold/
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
| `d1` | primary | `cursor_stream_holds_connection` | `src/main/java/com/example/slowquery/service/ReportExportService.java:23` | `lead` | `streamExport`（`@Transactional`，见同文件 line 19）在事务边界内以 `Cursor<ReportRow>` 流式读取并对每行执行 `formatRow`（固定规模 CPU 加工）；连接在整段流式遍历期间被占用，并发达到池上限 4 时后续请求获取连接阻塞至超时 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `jvm_gc_pause`。

> 说明：
> - `application.yml` 中的 `hikari.maximum-pool-size: 4` 与 `connection-timeout: 3000` 是**环境参数**，用于让占用可观测，**不是**缺陷本身；`formatRow` 的逐行加工耗时也**不是**缺陷本身，主根因在 `ReportExportService.streamExport` 把整段游标遍历放进了单个事务。
> - `streamRows` 是一条可走 `idx_report_region_id` 的单表查询，故 `missing_index` / `slow_query` 不是根因；循环内没有逐行回查，`n_plus_one` 也不是根因。问题在「连接持有时长」而非「SQL 本身」。
> - `code_location` 锚点取游标打开行（`:23`）；其所属事务注解 `@Transactional` 在同文件 `:19`，二者相距 4 行，均在 `code_location_hit` 默认 ±5 行容差内。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万条 report_rows）
mvn spring-boot:run

# 3. 触发症状（并发请求，使流式导出占满池上限 4，后续请求获取连接超时）
curl "http://localhost:8080/api/reports/stream-export?limit=20000"
```

## 评估要点

- 边界用例（问题类型 `connection_pool`，等待 Agent 支持）：**不可由单变量索引实验证实**；且当前 Agent 的 `ProblemKind` 仅支持 `slow_query` / `n_plus_one` / `deep_pagination`、`Finding.verified_requires_structural_evidence` 要求 `kind ∈ {slow_query, n_plus_one, deep_pagination}`，故在本用例上不可能产出 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- `decision_match`：期望 `lead`（Agent 若给出 `verified` 即触发 `false_verified` 硬闸门）。
- `limitation_declared`：必须声明三条 `expected.limitations_required`（并发窗口依赖、问题类型未支持、量化需连接池指标且该查询可走索引）。
- `false_verified` 硬闸门：任何为连接池问题伪造 `verified` 的输出直接判负。
- **待支持标注**：等待 Agent 支持 `connection_pool` 问题类型。

## 与其它用例的关系

- 与 `case-32`（`connection_pool` / `connection_held_across_remote_call`）区分：`case-32` 是**事务边界内同步调用远程支付网关**，连接持有时长由远程 I/O 拉长；本用例循环内**没有远程调用**，连接被拉长是因为**游标流式遍历 + 逐行加工整体被放进事务**。
- 与 `case-41`（`connection_pool` / `connection_held_across_response_stream`）区分：`case-41` 是在**事务内把结果分块写出 HTTP 响应、受慢客户端背压**而占用连接；本用例不写响应，占用来自**数据库侧游标流式读取**本身。
- 与 `case-17`（`connection_pool` / `connection_hold`）区分：`case-17` 是**后台任务轮询 sleep 期间**手写持有连接；本用例是请求路径上的声明式事务 + 游标遍历。
- 与 `case-09`（`connection_pool` / `connection_leak`）区分：`case-09` 正常路径下从不归还、跨调用累积；本用例连接会正常归还，仅因事务跨越整段流式遍历而在并发下被长时间占用。
- 与 `case-28`（`connection_pool` / `nested_connection_acquire`）区分：本用例单请求只占用 1 个连接。
- 与 `case-16` / `case-26` / `case-27` / `case-31` / `case-36` / `case-37` / `case-38`（`n_plus_one`）区分：本用例循环内不做逐行数据库回查，问题不在往返次数。
