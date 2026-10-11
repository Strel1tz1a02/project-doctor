# case-29-connection-pool-growth-task-discard

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `connection_pool` |
| `difficulty` | `hard` |
| 期望结论 | `lead` |
| 来源 | 改编自 [brettwooldridge/HikariCP](https://github.com/brettwooldridge/HikariCP)（Apache-2.0，`source=adapted`） |

设计意图：连接池在 `borrow()` 路径上**按需异步扩容**，把补建连接的任务提交给一个**单线程 + 有界队列 + `DiscardPolicy`** 的执行器。并发借连接时，超出队列容量的补建任务被**静默丢弃**，但 `allocated` 计数已经加过——池因此**误判已达上限而不再扩容**，实际连接数远低于上限，等待 `borrow` 的任务被拖到 `borrow-timeout`。用例考察 Agent 是否能：

1. 识别「低并发正常、并发升高才恶化」的资源特征，并把它归因到**扩容任务被丢弃 + 计数虚高**，而非慢 SQL、缺索引或 N+1；
2. 在问题类型尚未被 Agent 支持时给出 `lead` 结论并**显式声明限制**（不得伪造 `verified`）；
3. 不把连接池上限/队列容量这类环境参数、也不把单个任务内部的 `COUNT(*)` 误判为根因（该查询均可走索引）。

## 上游来源与原汁原味的保留

- 上游：`brettwooldridge/HikariCP`（许可证 Apache-2.0，已确认）。
- 保留的原汁原味：连接池在需要补充/扩容连接时，把补建任务提交到**带丢弃策略**的执行器；队列满时任务被静默丢弃，池无法达到预期容量而饥饿（参考 `HikariPool` 中的 `new CustomDiscardPolicy()` 与 `addBagItem` 路径，对应度较高的上游线索为 Issue #2378）。
- 按数据集约定的改造：上游为 Java 库（无 Web 入口），本项目按统一骨架改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；暴露 `GET /api/pool/ingest` 以并发入库任务触发借连接；判分指标统一为可实测字段 `duration_ms`；池容量收敛为 12、扩容队列容量 2、借连接超时 3000ms，使扩容失效在秒级稳定复现。

## 目录结构

```text
case-29-connection-pool-growth-task-discard/
├─ case.json                # 问题卡（ground truth）
├─ README.md                # 本文件（含答案，隔离）
└─ project/                 # 被测项目（Spring Boot + MyBatis + MySQL），唯一暴露给 Agent 的目录
   ├─ pom.xml
   ├─ docker-compose.yml
   ├─ README.md             # 面向 Agent 的项目说明（已脱敏）
   └─ src/main/...
      ├─ java/com/example/slowquery
      │  ├─ SlowQueryApplication.java
      │  ├─ config/PoolConfig.java          # 构建内置连接池（注入 app.pool.* 参数）
      │  ├─ controller/PoolIngestController.java
      │  ├─ dto/IngestResultVO.java
      │  ├─ init/DataInitRunner.java        # 初始化 20 万条 task_events
      │  ├─ pool/SimpleConnectionPool.java  # 关键缺陷：按需异步扩容 + DiscardPolicy
      │  └─ service/PooledIngestService.java
      └─ resources
         ├─ application.yml
         └─ schema.sql
```

## 缺陷清单

`path` 均相对 `project/`。

| defect_id | role | kind | 位置 | 期望状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `d1` | primary | `pool_growth_task_discard` | `src/main/java/com/example/slowquery/pool/SimpleConnectionPool.java:79`（`expandIfNeeded`，扩容任务提交点）<br/>`...:40`（构造函数，`new ThreadPoolExecutor.DiscardPolicy()`） | `lead` | `borrow()` 调用 `expandIfNeeded()`：只要 `allocated < maxSize` 就 `allocated+1` 并把补建任务提交给『单线程 + `ArrayBlockingQueue(2)` + `DiscardPolicy`』的执行器；队列满后补建任务被静默丢弃，但 `allocated` 已加，池误判已达上限 12 而不再扩容，实际连接仅约 3 条，等待 `borrow` 的任务超时 |

期望命中根因：`d1`（两处位置任一处命中即在容差内，机制本身横跨「扩容任务提交」(line 79) 与「丢弃策略」(line 40)）。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `jvm_gc_pause`。

> 说明：
> - `application.yml` 中的 `app.pool.max-size: 12`、`app.pool.queue-capacity: 2`、`app.pool.queue-threads: 1`、`app.pool.borrow-timeout-ms: 3000` 是**环境参数**，用于让扩容失效可观测，**不是**缺陷本身；主根因在 `SimpleConnectionPool` 的扩容提交与丢弃策略组合，以及 `allocated` 计数与实际连接数脱钩。
> - 每个入库任务内部的 `SELECT COUNT(*) FROM task_events WHERE shard = ?` 是**可走 `idx_task_events_shard` 的单条查询**，故 `missing_index` / `slow_query` 不是根因，也不存在 N+1 往返；问题在「扩容任务被丢弃」而非「SQL 本身」。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万条 task_events）
mvn spring-boot:run

# 3. 触发症状（并发请求，使借连接集中发生，超出真实连接数，尾部请求超时）
curl "http://localhost:8080/api/pool/ingest?workers=16"
```

> 复现要点：单请求低并发下 `allocated` 尚能跟上、不超时；需以较高并发（如多路并发请求、或提高 `workers`）使借连接集中发生，才能让被丢弃的扩容任务暴露为 `borrow` 超时。

## 评估要点

- 边界用例（问题类型 `connection_pool`，等待 Agent 支持）：**不可由单变量索引实验证实**；且当前 Agent 的 `ProblemKind` 仅支持 `slow_query`、`Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`，故在本用例上不可能产出 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- `decision_match`：期望 `lead`（Agent 若给出 `verified` 即触发 `false_verified` 硬闸门）。
- `limitation_declared`：必须声明三条 `expected.limitations_required`（并发窗口依赖、问题类型未支持、量化需连接池指标且单查询走索引）。
- `false_verified` 硬闸门：任何为连接池问题伪造 `verified` 的输出直接判负。
- **待支持标注**：等待 Agent 支持 `connection_pool` 问题类型。

## 与其它用例的关系

- 与 `case-17`（`connection_pool` / `connection_hold`）区分：`case-17` 是**在轮询等待期间持有连接**（持有范围跨越 sleep），池本身扩容正常；本用例是**扩容任务被丢弃导致池无法扩容**，连接会被正常归还，问题在容量无法增长。
- 与 `case-28`（`connection_pool` / `nested_connection_acquire`）区分：`case-28` 是**在持有外层连接的作用域内嵌套取连接**（持有与取连接相互嵌套），池能扩到上限；本用例是**池自身扩容失效**（计数虚高、任务被丢弃），二者机制不同。
- 与 `case-09`（`connection_pool` / `connection_leak`）区分：`case-09` 是正常路径下从不归还、跨调用累积泄漏；本用例连接会归还，仅因扩容任务被丢弃使池无法长到上限。
- 与 `case-16` / `case-26` / `case-27`（`n_plus_one`）区分：本用例单个任务内部只有一条可走索引的 `COUNT(*)`，不存在往返次数问题，故在 `expected.excluded_explanations` 中排除 `n_plus_one`。
