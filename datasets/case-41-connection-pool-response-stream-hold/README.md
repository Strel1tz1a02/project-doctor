# case-41-connection-pool-response-stream-hold

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `connection_pool` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自常见的「导出/下载接口在事务内一边持有连接一边向慢客户端分块流式写响应」场景（`source=adapted`，上游许可证待核验） |

设计意图：导出方法被标注 `@Transactional`，方法体内**先用一条可走索引的查询取一批数据，再在同一事务边界内逐行加工、并逐块写入 HTTP 响应的输出流（每块 flush）**。当客户端消费偏慢时，写/flush 会被下游背压阻塞，而这段写出位于事务方法体内，**数据库连接在整个响应写出期间一直被占用**。池上限为 4，并发请求数达到池上限时全部连接都被这类长响应写出的请求占用，其余请求在获取连接处阻塞直至 `connection-timeout(3000ms)` 并失败；冷启动单请求（客户端消费快）可正常返回，仅并发升高且客户端偏慢时恶化。用例考察 Agent 是否能：

1. 识别「冷启动单请求正常、并发升高才恶化」的资源占用特征，并把它归因到**响应流写出被放在数据库事务边界内、连接被响应写出时长支配**，而非慢 SQL、缺索引、N+1 或远程调用；
2. 在问题类型尚未被 Agent 支持时给出 `lead` 结论并**显式声明限制**（不得伪造 `verified`）；
3. 不把连接池上限、逐块加工耗时这类环境/实现参数误判为根因（`findRows` 单条查询可走索引）。

## 上游来源与原汁原味的保留

- 上游：常见的「导出/下载接口在数据库事务内一边持有连接一边向（可能很慢的）客户端分块流式写响应」工程模式（许可证待核验，不臆断具体仓库/提交）。
- 保留的原汁原味：处理流程为「开事务 → 查询取数 → 在事务边界内向响应流逐块写出 → 方法返回时提交」，连接持有时长等于整段响应写出时长。
- 按数据集约定的改造：统一改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0 骨架；逐行加工以固定规模 CPU 计算模拟，逐块 flush 模拟向慢客户端写出的背压；判分指标统一为可实测字段 `duration_ms`；连接池上限收敛为 4，使并发下的饥饿在秒级稳定复现。

## 目录结构

```text
case-41-connection-pool-response-stream-hold/
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
| `d1` | primary | `connection_held_across_response_stream` | `src/main/java/com/example/slowquery/service/ChunkedExportService.java:24` | `lead` | `streamChunked`（`@Transactional`，见同文件 line 23）在事务边界内查询取数、逐行加工并逐块 `out.write`/`out.flush` 写出 HTTP 响应；连接在整段（可能被慢客户端背压阻塞的）响应写出期间被占用，并发达到池上限 4 时后续请求获取连接阻塞至超时 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `jvm_gc_pause`。

> 说明：
> - `application.yml` 中的 `hikari.maximum-pool-size: 4` 与 `connection-timeout: 3000` 是**环境参数**，用于让占用可观测，**不是**缺陷本身；`formatChunk` 的逐行加工耗时也**不是**缺陷本身，主根因在 `ChunkedExportService.streamChunked` 把可能被慢客户端长期阻塞的响应流写出整体放进了单个事务。
> - `findRows` 是一条可走索引（`ORDER BY id` 走主键）的单表查询，故 `missing_index` / `slow_query` 不是根因；循环内没有逐条回查，`n_plus_one` 也不是根因；循环内也没有外部服务调用。问题在「连接持有时长」而非「SQL 本身」。
> - `code_location` 锚点取方法声明行（`:24`）；其所属事务注解 `@Transactional` 在同文件 `:23`（相距 1 行），响应写出循环在同文件 `:29`–`:30`（相距 5~6 行），主要落点均在 `code_location_hit` 默认 ±5 行容差内。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万条 export_rows）
mvn spring-boot:run

# 3. 触发症状（并发 + 慢客户端消费，使长响应写出的请求占满池上限 4，后续请求获取连接超时）
curl "http://localhost:8080/api/export/chunked-stream?chunks=8000"
```

## 评估要点

- 边界用例（问题类型 `connection_pool`，等待 Agent 支持）：**不可由单变量索引实验证实**；且当前 Agent 的 `ProblemKind` 仅支持 `slow_query` / `n_plus_one` / `deep_pagination`、`Finding.verified_requires_structural_evidence` 要求 `kind ∈ {slow_query, n_plus_one, deep_pagination}`，故在本用例上不可能产出 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- `decision_match`：期望 `lead`（Agent 若给出 `verified` 即触发 `false_verified` 硬闸门）。
- `limitation_declared`：必须声明三条 `expected.limitations_required`（并发窗口+慢客户端依赖、问题类型未支持、量化需连接池指标且该查询可走索引）。
- `false_verified` 硬闸门：任何为连接池问题伪造 `verified` 的输出直接判负。
- **待支持标注**：等待 Agent 支持 `connection_pool` 问题类型。

## 与其它用例的关系

- 与 `case-39`（`connection_pool` / `cursor_stream_holds_connection`）区分：`case-39` 连接被拉长是因为**数据库侧游标流式遍历 + 逐行加工整体被放进事务**，占用发生在读路径的游标上；本用例不从数据库侧流式读取（`findRows` 一次性取回一批），连接被拉长是因为**向 HTTP 响应的分块写出位于事务边界内、受慢客户端背压**。
- 与 `case-32`（`connection_pool` / `connection_held_across_remote_call`）区分：`case-32` 是**事务边界内同步调用远程支付网关**，连接持有时长由远程 I/O 拉长；本用例循环内**没有外部服务调用**，占用来自**对客户端的响应写出**。
- 与 `case-40`（`connection_pool` / `hot_row_lock_holds_connection`）区分：`case-40` 占用来自**热点行悲观锁使事务串行排队**；本用例不涉及行锁，占用来自**响应流写出**。
- 与 `case-17`（`connection_pool` / `connection_hold`）区分：`case-17` 是**后台任务轮询 sleep 期间**手写持有连接；本用例是请求路径上的声明式事务 + 响应流写出。
- 与 `case-09`（`connection_pool` / `connection_leak`）区分：`case-09` 正常路径下从不归还、跨调用累积；本用例连接会正常归还，仅因事务跨越整段响应写出而在并发下被长时间占用。
- 与 `case-28`（`connection_pool` / `nested_connection_acquire`）区分：本用例单请求只占用 1 个连接。
- 与 `case-29`（`connection_pool` / `pool_growth_task_discard`）区分：本用例不涉及连接池动态扩容与任务丢弃，池大小固定为 4。
- 与 `case-16` / `case-26` / `case-27` / `case-31` / `case-36` / `case-37` / `case-38`（`n_plus_one`）区分：本用例循环内不做逐行数据库回查，问题不在往返次数。