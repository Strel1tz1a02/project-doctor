# case-11-connection-setup-per-request

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `connection_setup` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制；**等待 Agent 支持**） |

设计意图：项目存在**一个真实、机制明确的结构性缺陷**——`GET /api/orders/legacy-recent` 对应的
`LegacyReportService.loadRecent` **绕过 Spring 数据源/连接池**，每次请求都直接用
`DriverManager.getConnection(URL, USER, PASSWORD)` 新建一条数据库连接，在用完的
`try-with-resources` 中正常关闭。

每次调用都必须付出**固定的 TCP 建连 + MySQL 握手/认证开销**，该开销与 SQL 本身无关：
查询 `SELECT id, order_no, amount FROM orders ORDER BY id DESC LIMIT ?` 走主键、只取几十行、
执行计划毫无问题，但整条请求的耗时仍被“建连握手”主导，且连接数随请求量呈锯齿状 churn。

与 `slow_query` 系用例不同，本用例的缺陷**不是靠执行计划**体现的：单条查询本就走主键。真正
的开销是**每请求重新建立连接**。理想情况下可由「对比每请求新建连接 vs 连接池复用」的变量实验
证实，但当前 Agent 的 `ProblemKind` 仅支持 `slow_query`（且
`Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`），因此**在本用例上
不可能产出 `verified`**，期望结论只能是 **`lead`**，并必须显式声明限制。

用例用于在 Agent 扩展问题类型之前，先检验其是否能：

1. 识别「查询本身很快、耗时却是固定建连开销」这一 `connection_setup` 特征；
2. 给出正确的定位（`DriverManager.getConnection(...)` 调用点）；
3. 正确区分本缺陷与 `connection_leak`（本用例连接已正常关闭，不是泄漏）；
4. 如实声明「无法证实为 `verified`」及原因（等待 Agent 支持新问题类型），而非勉强下结论或误报 `false_verified`。

## 目录结构

```text
case-11-connection-setup-per-request/
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
| `d1` | primary | `per_request_connection_setup` | `.../service/LegacyReportService.java:19` | `lead` | `loadRecent` 每次调用都用 `DriverManager.getConnection(URL, USER, PASSWORD)` 新建连接，固定付出 TCP 建连 + MySQL 握手/认证开销；查询本身走主键、很快，开销与 SQL 无关，连接数随请求呈锯齿状 churn；连接在 try-with-resources 中正常关闭，**不是泄漏** |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `connection_leak` / `jvm_gc_pause`。

主缺陷所在行的原文：

```java
        try (Connection conn = DriverManager.getConnection(URL, USER, PASSWORD);
```

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/orders/legacy-recent?size=50"
```

## 评估要点

- 关键观察：`legacy-recent` 的 P95 明显高于 `by-user`；耗时以固定建连开销为主，且不随 `size` 明显变化（查询很快）。
- 可证实性：**无法**由单变量索引实验证实（SQL 走主键 LIMIT、执行计划无问题）；只能以“每请求新建连接”的结构特征佐证，故期望 `lead` 而非 `verified`。
- 关键区分：`legacy-recent` 的连接在 `try-with-resources` 中关闭，**不是** `connection_leak`；`connection_leak` 应作为被排除的解释。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条，含「等待 Agent 支持」）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。
- **待支持标注**：当前 `ProblemKind` 不含 `connection_setup`，本用例归档为「等待 Agent 支持」；待 Agent 扩展问题类型后，可重判为 `normal`（若届时能由连接复用实验证据闭环）。

## 与其它用例的关系

- 与 `case-09-connection-pool-leak` 互补：`case-09` 是「取了连接从不归还」（池被耗尽、最终获取超时），
  本用例是「每请求新建连接且正常关闭」（固定建连开销、连接数 churn）；两者共用连接主题但机制相反，
  用于检验 Agent 能否区分 `connection_leak` 与 `connection_setup`。
- 与 `case-07-n-plus-one-order-user`、`case-08-deep-pagination-large-offset` 同属「问题类型待 Agent 支持」的
  预置用例，均为 `boundary / lead`。
- 与 `slow_query` 系用例的区别：本用例的耗时**不体现在执行计划**上，不能用单变量索引实验证实，正是其被定为 `boundary` 的原因。
