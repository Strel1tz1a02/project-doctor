# case-22-thread-pool-input-starvation

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `thread_pool` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制；**等待 Agent 支持**） |
| 来源 | 改编自 [socket-link/ampere](https://github.com/socket-link/ampere) Issue #182（Apache-2.0，`source=adapted`） |

设计意图：项目存在**一个真实、机制明确的结构性缺陷**——`AsyncOrderService` 用**同一个固定 4 线程的 `ThreadPoolExecutor`（`dispatcher`）**承载两类任务：

- **交互式快照** `asyncRecent(...)`：短查询任务，提交到 `dispatcher` 后同步 `get()`；
- **阻塞式分析** `analyze(userId, rounds)`：把 `rounds` 个阻塞式“推理”任务（池内 `sleepQuietly(500)` 模拟推理耗时）提交到**同一个** `dispatcher`。

一次 `analyze(rounds=8)` 会把 8 个阻塞任务排入同一调度器：前 4 个立即**占满全部 4 个线程**，其余 4 个排在队列里。此期间任何提交到同一 `dispatcher` 的 `asyncRecent` 只能**排在阻塞任务之后等待**，直到有线程腾出为止——交互式请求的输入延迟被**饿死**（个位数毫秒 → 数百毫秒以上）。`analyze` 结束后随即回落。

与 `slow_query` 系用例不同，本用例的缺陷**不是靠执行计划**体现的：查询按 `user_id` 走 `idx_orders_user_created` 且带 `LIMIT`，执行计划毫无问题。真正的成本是「把阻塞式工作与延迟敏感的交互式工作混在同一个有限调度器上、且未做隔离」。理想情况下可由「分析运行中 vs 空闲」两种负载的对比证实，但当前 Agent 的 `ProblemKind` 仅支持 `slow_query`（且 `Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`），因此**在本用例上不可能产出 `verified`**，期望结论只能是 **`lead`**，并必须显式声明限制。

用例用于在 Agent 扩展问题类型之前，先检验其是否能：

1. 识别「SQL 计划无问题、交互式请求却被排队饿死」这一 `thread_pool` 特征；
2. 给出正确的定位（**共享**的关键调度器 / 未隔离阻塞式工作）；
3. 如实声明「无法证实为 `verified`」及原因（等待 Agent 支持新问题类型），而非勉强下结论或误报 `false_verified`。

## 上游来源与原汁原味的保留

- 上游：`socket-link/ampere` Issue #182《P0: Fix Input Thread Starvation During Cognitive Processing》（labels `bug`/`cli`/`p0`，**Closed**，由 **PR #187** 关闭；Part of #181）——Jazz Test 执行期间 CLI 交互愈发无响应：`'h'` 帮助不触发、面板切换（1/2/3 键）响应很慢、`':'` 后每次键击延迟递增、Backspace 输入空格而非删除；判定为典型的**线程饥饿**（render loop / cognitive processing 独占 coroutine dispatcher）。技术要点含「确保 cognitive processing 运行在 `Dispatchers.IO`」（`WRONG: blocks main thread ... llmClient.complete(prompt)` vs `RIGHT: withContext(Dispatchers.IO) { ... }`）、render loop 须 `delay(100)` + `yield()`、输入处理独立 coroutine；验证标准「`'h'` 在活跃认知处理期间 100ms 内响应」。
- 上游关键位置（问题存在时）：认知处理与渲染/输入处理**共用同一 coroutine dispatcher** 的调度路径；问题存在时 HEAD `main@3bf7dfa36c982492c923852686cadf1846f426c3`；修复 commits `d7fcce777e6ae1c8421a078a30a0fe3ea1c8f534`、`4a0588ed1ee23417a9e63a493816d251b50c53ac`（`Fix input thread starvation during cognitive processing`），release `0.1.0`。
- 保留的原汁原味：
  - **「阻塞式任务独占共享调度器 → 饿死延迟敏感任务」** 这一机制逐字迁移：`AsyncOrderService` 用**同一个**固定 4 线程的 `dispatcher` 承载交互式快照与阻塞式分析任务，长任务占满线程后交互式请求被排队等待；
  - **两类工作的语义保留**：交互式请求（`async-recent`，对应上游的输入/渲染处理）+ 阻塞式长任务（`analyze` 的推理，对应上游 `llmClient.complete` 的认知处理）；
  - 上游修复方向（把阻塞式工作隔离到专用执行器 / `Dispatchers.IO`）在 `expected_fix` 中原样保留为「把阻塞式工作与交互式工作隔离到不同执行器」。
- 按数据集约定的改造：上游为 Kotlin（JLine3 + Kotlin Coroutines，CLI 场景），本项目按统一骨架改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；上游「协程 dispatcher 饥饿」在骨架内同构为「固定大小 `ThreadPoolExecutor` 饥饿」；上游「输入延迟」在骨架内落为 `async-recent` 的 `duration_ms`（可实测字段）；数据规模按数据集约定设定为 `orders=200000`。

主缺陷所在行的原文：

```java
    private final ThreadPoolExecutor dispatcher =
```

## 目录结构

```text
case-22-thread-pool-input-starvation/
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
| `d1` | primary | `dispatcher_starvation` | `src/main/java/com/example/slowquery/service/AsyncOrderService.java:26` | `lead` | 同一个固定 4 线程的 `dispatcher` 承载交互式快照与阻塞式分析任务；`analyze(rounds=8)` 的阻塞任务占满全部线程，并发提交的 `async-recent` 被排队饿死（输入延迟个位数毫秒 → 数百毫秒以上）；与 SQL 计划无关 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `connection_pool`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单）
mvn spring-boot:run

# 3. 触发症状：先启动分析，再并发调用交互式接口
curl "http://localhost:8080/api/orders/analyze?userId=123&rounds=8" &
curl "http://localhost:8080/api/orders/async-recent?userId=123&size=20"
```

## 评估要点

- 关键观察：`analyze` 运行期间，`async-recent` 的 P95 明显升高（被排队等待）；`analyze` 结束后回落；空闲基线为个位数毫秒。
- 可证实性：**无法**由单变量索引实验证实（查询走 `idx_orders_user_created` 且带 `LIMIT`，执行计划无问题），故期望 `lead` 而非 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条，含「等待 Agent 支持」）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。
- **待支持标注**：当前 `ProblemKind` 不含 `thread_pool`，本用例归档为「等待 Agent 支持」；待 Agent 扩展问题类型、并支持以调度器排队/隔离实验证据闭环后，可重判为 `normal`。

## 与其它用例的关系

- 与 `case-13-thread-pool-no-verifiable-defect`（`thread_pool`）互补：`case-13` 是**不可证实的失败用例**（线程池配置合理、队列常年近乎为空，无可证实根因，`failure / unclassified`）；本用例是**真实可复现的边界用例**（共享调度器被长任务占满、交互式请求被饿死，`boundary / lead`），二者共享统一骨架便于对照。
- 与 `case-09-connection-pool-leak` / `case-14-config-regression-pool-size` 的区别：后两者是**数据库连接池**问题（连接不归还 / 池被调小）；本用例是**应用内线程调度器**的饥饿，与数据库连接池无关，`connection_pool` 作为被排除的解释。
- 与 `case-07-n-plus-one-order-user`、`case-18` / `case-19` / `case-20` / `case-21` 同属「问题类型待 Agent 支持」的预置用例，均为 `boundary / lead`。
