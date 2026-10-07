# case-12-excessive-logging-sync-debug

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `excessive_logging` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制；**等待 Agent 支持**） |

设计意图：项目存在**一个真实、机制明确的结构性缺陷**——`GET /api/orders/by-user` 在 `recentByUser` 的 `for` 循环中，对**每一条**返回订单打印 `DEBUG` 日志；同时 `logback-spring.xml` 配置了一个**同步** `FileAppender`（`<immediateFlush>true</immediateFlush>`）写入 `logs/app.log`。单次请求 `size=500` 即产生数百条同步写盘操作，耗时随返回行数近似线性增长。

与 `slow_query` 系用例不同，本用例的缺陷**不是靠执行计划**体现的：`project/src/main/resources/schema.sql` 已为 `orders` 增加 `idx_orders_user_created (user_id, created_at)`，`by-user` 查询走索引、本身很快，**唯一瓶颈只剩日志**（这也刻意消除了 `case-04` 基座自带的缺索引干扰）。理想情况下可由「降低日志级别 / 改用异步 appender 后时延显著下降」证实，但当前 Agent 的 `ProblemKind` 仅支持 `slow_query`（且 `Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`），因此**在本用例上不可能产出 `verified`**，期望结论只能是 **`lead`**，并必须显式声明限制。

用例用于在 Agent 扩展问题类型之前，先检验其是否能：

1. 识别「SQL 计划正常、耗时却随返回行数线性增长」这一热路径日志放大的特征；
2. 给出正确的定位（循环内逐行 `log.debug` 的调用点）；
3. 如实声明「无法证实为 `verified`」及原因（等待 Agent 支持新问题类型），而非勉强下结论或误报 `false_verified`。

## 目录结构

```text
case-12-excessive-logging-sync-debug/
├─ case.json                # 问题卡（ground truth）
├─ README.md                # 本文件（含答案，隔离）
└─ project/                 # 被测项目（Spring Boot + MyBatis + MySQL），唯一暴露给 Agent 的目录
   ├─ pom.xml               # artifactId / name = order-exlogging
   ├─ docker-compose.yml    # container_name = order-exlogging-mysql
   ├─ README.md             # 面向 Agent 的项目说明（已脱敏）
   └─ src/main/...
      ├─ java/com/example/slowquery/service/OrderService.java   # 热路径逐行 DEBUG 日志
      └─ resources
         ├─ application.yml        # logging.level.com.example.slowquery: debug
         ├─ logback-spring.xml     # ConsoleAppender + 同步 FileAppender(logs/app.log, immediateFlush=true)
         └─ schema.sql             # orders 含 idx_orders_user_created(user_id, created_at)
```

## 缺陷清单

`path` 均相对 `project/`。

| defect_id | role | kind | 位置 | 期望状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `d1` | primary | `synchronous_verbose_logging` | `src/main/java/com/example/slowquery/service/OrderService.java:29` | `lead` | `recentByUser` 的 for 循环内对每条订单 `log.debug`，配合同步 `FileAppender`（`immediateFlush=true`），单请求数百条同步写盘，耗时随行数线性增长；查询走 `idx_orders_user_created`、无缺索引 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `connection_pool`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/orders/by-user?userId=123&size=500"
```

## 评估要点

- 关键观察：请求耗时随 `size` 增大而近似线性增长；日志量巨大、`logs/app.log` 迅速膨胀；`size` 较小时不可观测。
- 可证实性：可尝试「降级日志级别 / 改异步 appender」佐证耗时下降；但由于问题类型不支持，**无法**产出 `verified`，故期望 `lead`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条，含「等待 Agent 支持」）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。
- **待支持标注**：当前 `ProblemKind` 不含 `excessive_logging`，本用例归档为「等待 Agent 支持」；待 Agent 扩展问题类型后，可重判为 `normal`（若届时能由日志级别/异步 appender 实验闭环）。

## 与其它用例的关系

- 与 `case-04-slow-query-user-index` 同基座但方向相反：`case-04` 以**缺索引**为唯一主缺陷（查询慢）；本用例在 `schema.sql` 中**补上 `idx_orders_user_created`** 消除索引干扰后，把 `excessive_logging` 作为**唯一 primary** 独立成卡，用于检验 Agent 是否会被「代码结构导致的写盘放大」误导。
- 与 `case-13-thread-pool-no-verifiable-defect`、`case-14-config-regression-pool-size` 同属在 `case-04` 基座上「补索引后」的分支用例，均把 SQL 计划因素排除，聚焦非 `slow_query` 类问题。
- 与 `slow_query` 系用例的区别：本用例的耗时**不体现在执行计划**上，不能用单变量索引实验证实，正是其被定为 `boundary` 的原因。
