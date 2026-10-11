# case-23-config-regression-summary-limit

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `config_regression` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制；**等待 Agent 支持**） |
| 来源 | 改编自 [dahlia/optique](https://github.com/dahlia/optique) PR #777（MIT，`source=adapted`） |

设计意图：项目存在**一个真实、机制明确的结构性缺陷**——摘要接口的行数上限由 `config/SummaryLimitResolver` 解析：

- **显式配置路径**：`report.summary.limit` 存在且合法时，`resolve()` 解析后调用 `clamp(...)` 夹取到 `[1, HARD_MAX=100]`；
- **回退路径**：配置缺失（配置迁移后该键未被带过来）或不合法时，走 `fallback()`，**直接返回默认值 `5000`，未套用同一 `clamp`**。

两条路径行为不一致：回退值绕过了硬上限约束，下游 `OrderService.summary()` 以该值作为 `LIMIT`，导致 `GET /api/orders/summary` 返回行数由约 100 暴涨到约 5000。该查询本身是 `ORDER BY id DESC LIMIT n`、走主键、执行计划正常；接口不报错、HTTP 200；同库的 `/api/orders/by-user` 一切正常。

与 `slow_query` 系用例不同，本用例的缺陷**不是靠执行计划**体现的：真正的问题是「配置回退值未被重新校验、绕过了上限约束」。理想情况下可由「对照显式配置 + 修正回退路径后重测行数」证实，但当前 Agent 的 `ProblemKind` 仅支持 `slow_query`（且 `Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`），因此**在本用例上不可能产出 `verified`**，期望结论只能是 **`lead`**，并必须显式声明限制。

用例用于在 Agent 扩展问题类型之前，先检验其是否能：

1. 识别「接口不报错、SQL 计划正常、代码未改动、却返回远超约定上限的行数」这一 `config_regression` 特征；
2. 给出正确的定位（**配置/回退层**的上限校验缺失，而非任何单条 SQL）；
3. 如实声明「无法证实为 `verified`」及原因（等待 Agent 支持新问题类型），而非勉强下结论或误报 `false_verified`。

## 上游来源与原汁原味的保留

- 上游（许可来源）：[`dahlia/optique`](https://github.com/dahlia/optique) **PR #777**《Revalidate fallback values in `bindEnv()` and `bindConfig()`》（**Merged**，Fixes **#414**，许可证 **MIT**；关键位置 `packages/env/src/index.ts`、`packages/config/src/index.ts`、`packages/core/src/primitives.ts`、`packages/core/src/modifiers.ts`）。核心机制：`bindEnv()` / `bindConfig()` 在取用回退值时**未重新经过内层 CLI parser 的校验**，使 `string({pattern})` / `integer({min})` / `choice()` 等约束可被静默绕过；修复方向是新增 `Parser.validateValue()`，让回退值同样走一遍校验。
- 原候选（未采用）：[`tphakala/birdnet-go`](https://github.com/tphakala/birdnet-go) Issue #2361《Add API default-parameter regression tests》（关联 #2352，**Closed**）——配置迁移导致默认值回退、`GORM Limit(0)` 返回 0 行；同一 `config_migration_default_regression` 机制。因该仓库根目录许可证为 **CC BY-NC-SA 4.0（非商用）**，**未采用**，仅作机制佐证。
- 保留的原汁原味：
  - **「回退值绕过内层校验」** 这一机制逐字迁移：`SummaryLimitResolver.fallback()` 直接返回 `FALLBACK_DEFAULT`（5000），未套用显式配置路径同款的 `clamp(HARD_MAX)`；
  - **两条路径行为不一致** 的语义保留：显式配置路径正常夹取到 `[1, HARD_MAX]`，回退路径不受同一约束（对应上游 parser 约束在回退时被跳过）；
  - 上游修复方向（让回退值同样走校验路径）在 `expected_fix` 中原样保留为「对回退值同样套用校验/夹取」。
- 按数据集约定的改造：上游为 TypeScript（`packages/env`、`packages/config`、`packages/core`），本项目按统一骨架改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；上游「parser 约束被回退绕过」在骨架内同构为「摘要上限的 `clamp` 被 `fallback()` 绕过」；上游「配置项缺失」在骨架内落为 `report.summary.limit` 缺失（`application.yml` 中**刻意不写该键**）；判分指标统一为可实测字段 `rows_returned`（约定上限 100 vs 实测约 5000）；表与初始化沿用统一 `orders` 骨架（`orders=200000`）。

主缺陷所在行的原文：

```java
        return FALLBACK_DEFAULT;
```

## 目录结构

```text
case-23-config-regression-summary-limit/
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
| `d1` | primary | `fallback_default_bypasses_validation` | `src/main/java/com/example/slowquery/config/SummaryLimitResolver.java:48` | `lead` | 摘要上限回退分支 `fallback()` 直接返回默认值 5000，未套用与显式配置路径相同的 `clamp(HARD_MAX)`；回退值绕过硬上限，下游以其作 `LIMIT`，返回行数由约 100 涨到约 5000；查询为 `ORDER BY id DESC LIMIT n`、走主键、计划正常 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单）
mvn spring-boot:run

# 3. 触发症状：摘要接口返回的行数远超约定上限
curl "http://localhost:8080/api/orders/summary"
```

## 评估要点

- 关键观察：`GET /api/orders/summary` 返回约 5000 行，远超约定上限（约 100）；HTTP 200、不报错；对照 `/api/orders/by-user` 一切正常。
- 可证实性：**无法**由单变量 SQL 实验证实（查询走主键、执行计划无问题）；真正依赖的是「配置缺失/被迁移」这一条件与「回退值未重新校验」这一代码事实，故期望 `lead` 而非 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条，含「等待 Agent 支持」）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。
- **待支持标注**：当前 `ProblemKind` 不含 `config_regression`，本用例归档为「等待 Agent 支持」；待 Agent 扩展问题类型、并支持以「配置/回退路径 + 对照实验」证据闭环后，可重判为 `normal`。

## 与其它用例的关系

- 与 `case-14-config-regression-pool-size`（`config_regression`）对位：二者均为 `boundary / lead`。区别在**缺陷落点**——`case-14` 是「连接池上限被调小」（配置值本身生效、导致连接等待），本用例是「配置/回退值的**校验缺失**」（回退值绕过上限、导致返回行数暴涨），同属 `config_regression` 但机制不同，便于对照 Agent 的归因粒度。
- 与 `case-09-connection-pool-leak` 的区别：`case-09` 是**连接不归还**导致的池泄漏；本用例与连接池无关，`connection_pool` 不在本用例的排除集合内（本用例排除的是 `missing_index` / `slow_query` / `n_plus_one` / `jvm_gc_pause`）。
- 与 `case-07-n-plus-one-order-user`、`case-18` / `case-19` / `case-20` / `case-21` / `case-22` 同属「问题类型待 Agent 支持」的预置用例，均为 `boundary / lead`。
