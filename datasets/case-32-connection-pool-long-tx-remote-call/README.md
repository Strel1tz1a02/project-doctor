# case-32-connection-pool-long-tx-remote-call

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `connection_pool` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自常见的「对账/结算批处理在事务内同步调用第三方支付网关」场景（`source=adapted`，上游许可证待核验） |

设计意图：对账批处理方法被标注 `@Transactional`，**事务在方法开始时借出连接并一直持有到方法返回**；方法体在事务边界**内**对每条任务**串行调用外部支付网关**（远程调用，每次约 250ms）。于是数据库连接被占用的时长 ≈ `batch × 250ms`（batch=20 时约 5s），远超 `connection-timeout(3000ms)`。池上限为 4，并发请求数达到池上限时连接被长事务耗尽，后续请求获取连接超时。用例考察 Agent 是否能：

1. 识别「冷启动单请求正常、并发升高才恶化」的资源占用特征，并把它归因到**事务边界包含了耗时的远程调用**（连接持有时长被远程 I/O 拉长），而非慢 SQL、缺索引或 N+1；
2. 在问题类型尚未被 Agent 支持时给出 `lead` 结论并**显式声明限制**（不得伪造 `verified`）；
3. 不把连接池上限、网关调用耗时这类环境/外部参数误判为根因（`findPendingTasks` 可走索引、`markSettled` 走主键）。

## 上游来源与原汁原味的保留

- 上游：常见的「对账/结算批处理在数据库事务内同步调用第三方支付网关」工程模式（许可证待核验，不臆断具体仓库/提交）。
- 保留的原汁原味：处理流程为「开事务 → 读取一批任务 → 在事务内逐条调用远程支付网关 → 写回结果 → 提交」，事务把远程调用耗时也算入连接持有时长。
- 按数据集约定的改造：统一改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0 骨架；远程调用以固定 250ms 的阻塞调用模拟；判分指标统一为可实测字段 `duration_ms`；连接池上限收敛为 4，使并发下的饥饿在秒级稳定复现。

## 目录结构

```text
case-32-connection-pool-long-tx-remote-call/
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
| `d1` | primary | `connection_held_across_remote_call` | `src/main/java/com/example/slowquery/service/ReconcileService.java:29` | `lead` | `scanAndSettle`（`@Transactional`，见同文件 line 24）在事务边界内对每条任务串行调用 `paymentGatewayClient.authorize`（远程调用，约 250ms/条），连接在整个远程调用期间被占用；并发达到池上限 4 时后续请求获取连接阻塞至超时 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `jvm_gc_pause`。

> 说明：
> - `application.yml` 中的 `hikari.maximum-pool-size: 4` 与 `connection-timeout: 3000` 是**环境参数**，用于让占用可观测，**不是**缺陷本身；`PaymentGatewayClient` 中 250ms 的模拟耗时也**不是**缺陷本身，主根因在 `ReconcileService.scanAndSettle` 的事务边界包含了远程 I/O。
> - `findPendingTasks` 可走 `idx_reconcile_status_id`、`markSettled` 走主键，均为单条可走索引的语句，故 `missing_index` / `slow_query` 不是根因；问题在「连接持有时长」而非「SQL 本身」。
> - `code_location` 锚点取线上远程调用所在行（`:29`）；其所属事务注解 `@Transactional` 在同文件 `:24`，二者相距 5 行，均在 `code_location_hit` 默认 ±5 行容差内。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万条 reconcile_tasks）
mvn spring-boot:run

# 3. 触发症状（并发请求，使长事务占满池上限 4，后续请求获取连接超时）
curl "http://localhost:8080/api/reconcile/scan?batch=20"
```

## 评估要点

- 边界用例（问题类型 `connection_pool`，等待 Agent 支持）：**不可由单变量索引实验证实**；且当前 Agent 的 `ProblemKind` 仅支持 `slow_query`、`Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`，故在本用例上不可能产出 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- `decision_match`：期望 `lead`（Agent 若给出 `verified` 即触发 `false_verified` 硬闸门）。
- `limitation_declared`：必须声明三条 `expected.limitations_required`（并发窗口依赖、问题类型未支持、量化需连接池指标且各条 SQL 均走索引）。
- `false_verified` 硬闸门：任何为连接池问题伪造 `verified` 的输出直接判负。
- **待支持标注**：等待 Agent 支持 `connection_pool` 问题类型。

## 与其它用例的关系

- 与 `case-17`（`connection_pool` / `connection_hold`）区分：`case-17` 是在**后台任务的轮询等待（sleep）期间**以手写方式持有连接、循环内不再取连接；本用例是**声明式事务（`@Transactional`）在事务边界内同步调用远程网关**，连接由事务机制持有、持有时长由远程 I/O 拉长，属「事务边界包含远程调用」反模式，机制与修复方向不同（前者缩短持有范围，后者把远程调用移出事务）。
- 与 `case-28`（`connection_pool` / `nested_connection_acquire`）区分：`case-28` 是**持有外层连接期间嵌套取连接**（一次请求同时占用多个连接）；本用例单请求只占用 1 个连接，问题是**该连接被事务长期占用**，并发下耗尽池。
- 与 `case-09`（`connection_pool` / `connection_leak`）区分：`case-09` 是正常路径下从不归还、跨调用累积；本用例连接会正常归还，仅因事务跨越远程调用而在并发下被长时间占用。
- 与 `case-16` / `case-26` / `case-27` / `case-31`（`n_plus_one`）区分：本用例循环内的远程调用不产生数据库往返放大，数据库语句均为每次一条，问题不在往返次数，故在 `expected.excluded_explanations` 中排除 `n_plus_one`。
