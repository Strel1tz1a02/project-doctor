# case-09-connection-pool-leak

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `connection_pool` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制；**等待 Agent 支持**） |
| 主缺陷 | `d1`（`connection_leak`，`role=primary`） |

设计意图：项目存在**一个真实、机制明确的结构性缺陷**——`GET /api/orders/export` 在正常路径下从连接池取出连接后**从不归还**（`ReportService.exportRecentOrders` 内无 `try-with-resources`、无 `finally`、也不调用 `close()`）。数据源连接池上限被设为 `10`（`application.yml` 中 `spring.datasource.hikari.maximum-pool-size`），每调用一次便消耗一条连接，累计调用达到池上限后连接池被耗尽，后续请求在**获取连接处阻塞**直至 `connection-timeout`（3 秒）而失败/超时，表现为 P95 随累计调用次数逐步升高。

与 `slow_query` 系用例不同，本用例的缺陷**不是靠执行计划**体现的：导出查询按主键 `id` 倒序 `LIMIT ?`，执行计划毫无问题；真正的开销是**连接这一有限资源随调用次数被单向消耗且不回收**。理想情况下可由「连接池活跃连接数随时间单调增长」「获取连接超时计数上升」等指标证实，但当前 Agent 的 `ProblemKind` 仅支持 `slow_query`（且 `Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`），因此**在本用例上不可能产出 `verified`**，期望结论只能是 **`lead`**，并必须显式声明限制。

用例用于在 Agent 扩展问题类型之前，先检验其是否能：

1. 识别「冷启动单次调用正常、随累计调用次数逐步恶化」这一资源泄漏特征；
2. 给出正确的定位（取连接却未归还的那一行）；
3. 如实声明「无法证实为 `verified`」及原因（证据依赖持续并发窗口 + 等待 Agent 支持新问题类型），而非勉强下结论或误报 `false_verified`。

## 目录结构

```text
case-09-connection-pool-leak/
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
| `d1` | primary | `connection_leak` | `.../service/ReportService.java:21` | `lead` | `exportRecentOrders` 第一行 `Connection conn = dataSource.getConnection();` 取连接，但整段方法无 `try-with-resources`/`finally`/`close()`，正常路径下从不归还；池上限 10 被逐步耗尽，后续请求在获取连接处阻塞至 `connection-timeout` |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `jvm_gc_pause`。

> 说明：`application.yml` 中 `hikari.maximum-pool-size=10`、`connection-timeout=3000` 是**环境参数**（用于缩短耗尽观测窗口），其本身不是缺陷；本用例的 primary 根因是 `ReportService` 中「取连接不归还」的代码路径，故 `code_locations` 指向该代码行而非配置行。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单）
mvn spring-boot:run

# 3. 触发症状（持续并发调用）
curl "http://localhost:8080/api/orders/export?size=1000"
```

## 评估要点

- 关键观察：冷启动单次调用很快；在 `concurrency≈4` 的持续并发下，约在池容量（10）被耗尽后延迟阶跃上升并出现获取连接超时；因此需要**足够长的压测窗口**才能观测到恶化趋势。
- 可证实性：**无法**由单变量索引/执行计划实验证实（导出查询走主键、计划正常）；连接泄漏的量化需要「活跃连接数随时间增长」或「获取连接超时计数」类指标，仅凭 `duration_ms` 难与其它阻塞型缺陷完全区分，故期望 `lead` 而非 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条，含「等待 Agent 支持」）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。
- **待支持标注**：当前 `ProblemKind` 不含 `connection_pool`，本用例归档为「等待 Agent 支持」；待 Agent 扩展问题类型并能结合连接池指标闭环后，可重判。

## 与其它用例的关系

- 与 `case-11-connection-setup-per-request` 互为对照：`case-11` 的接口**每次新建连接且正常关闭**（固定建连开销，非泄漏）；本用例接口**复用池连接但从不归还**（渐进式耗尽）。两者同属 `problem_kind=connection_pool` 相关话题，但机制相反，用于检验 Agent 能否区分「固定开销」与「累积泄漏」。
- 与 `case-14-config-regression-pool-size` 的区别：`case-14` 中代码未改动、仅池上限被回退为极小值（配置问题）；本用例池上限正常（10）但**代码取连接不归还**（代码问题），`code_locations` 指向 Java 代码而非配置。
- 与 `case-07-n-plus-one-order-user`、`case-08-deep-pagination-large-offset` 同属「问题类型待 Agent 支持」的预置用例，均为 `boundary / lead`。
