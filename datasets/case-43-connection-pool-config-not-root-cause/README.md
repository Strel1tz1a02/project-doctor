# case-43-connection-pool-config-not-root-cause

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，且结论依赖并发窗口，只能给 `lead`） |
| `problem_kind` | `connection_pool` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| `expected.repair.expected_to_change` | `false`（**不该改**：期望保持克制，不改配置、不改代码） |
| 来源 | `handcrafted` |

设计意图：本用例是「克制（restraint）」系列之一，对应「**非缺陷/配置正常 → 不该改**」。现象是并发获取连接超时，最容易被误判为「连接池上限过小」并据此调大 `maximum-pool-size`；但池上限 20 已远高于实际并发峰值，真正的机制是**事务内 CPU 聚合导致连接持有范围过大**。用例考察 Agent 是否能：

1. 把「上限过小」这类环境参数与代码根因区分开，不把配置改动当修复；
2. 在问题类型未被 Agent 支持时给出 `lead` 并**显式声明限制**（不得伪造 `verified`）；
3. **保持克制：不改动连接池等配置、不改动代码、不产出补丁**。

## 目录结构

```text
case-43-connection-pool-config-not-root-cause/
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
| `d1` | primary | `connection_hold_across_cpu_aggregation` | `src/main/java/com/example/slowquery/service/ReconcileService.java:44` | `lead` | `reconcile` 在事务内完成 CPU 聚合后才提交，事务期间持续持有连接；并发接近池上限时其余请求获取连接超时 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `jvm_gc_pause`。

> 说明：`application.yml` 中的 `hikari.maximum-pool-size: 20` 与 `connection-timeout: 3000` 是**环境参数**，用于让占用可观测，**不是**缺陷本身；把它们当作根因并调大，是本用例要拒绝的「错误修复」。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/orders/reconcile?days=90"
```

## 评估要点

- 边界用例（问题类型 `connection_pool`，等待 Agent 支持）：不可由单变量索引实验证实；且当前 Agent 的 `ProblemKind` 仅支持 `slow_query` / `n_plus_one` / `deep_pagination`，本用例不可能产出 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- `decision_match`：期望 `lead`（若给出 `verified` 即触发 `false_verified` 硬闸门）。
- `limitation_declared`：必须声明三条 `expected.limitations_required`（并发窗口依赖、问题类型未支持、须保持克制）。
- **修复能力（克制）**：`expected.repair.expected_to_change = false`。未尝试改动则四项修复指标判为满足；一旦尝试改配置/代码即判负。这正是本用例要考察的「配置正常、不该改」。
- **待支持标注**：等待 Agent 支持 `connection_pool` 问题类型。

## 与其它用例的关系

- 与 `case-17`（`connection_pool` / boundary / `lead`）区分：`case-17` 是**连接持有范围跨越轮询等待**（外部 I/O 等待型），且有对应的上游来源；本用例是**连接持有范围跨越事务内 CPU 聚合**，核心考察点是**拒绝把「连接池上限」误判为根因并拒绝据此改配置**（`expected_to_change=false`）。
- 与 `case-09`（连接泄漏）区分：本用例无泄漏，连接最终会归还，问题在于单次调用内持有范围过大。
