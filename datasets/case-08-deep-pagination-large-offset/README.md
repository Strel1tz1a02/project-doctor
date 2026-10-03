# case-08-deep-pagination-large-offset

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `deep_pagination` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制；**等待 Agent 支持**） |

设计意图：项目存在**一个真实、机制明确的结构性缺陷**——`GET /api/orders/page` 采用 `LIMIT #{offset}, #{size}` 深分页。深页时 `offset = (page-1)*size` 接近全表行数（`page=10000`、`size=20` 时 `offset=199980`），MySQL 必须沿 `idx_orders_created_at` **顺序扫描并丢弃前 offset 行**才返回本页，代价随翻页深度**线性增长**。

与 `slow_query` 系用例不同，本用例的缺陷**不是靠执行计划/缺索引**体现的：`orders` 已具备 `idx_orders_created_at`，`ORDER BY created_at DESC` 本身走索引。真正的开销是**为跳过 offset 行所做的无效扫描**。理想情况下可由「对比深浅页耗时随 offset 的变化」佐证，但当前 Agent 的 `ProblemKind` 仅支持 `slow_query`（且 `Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`），因此**在本用例上不可能产出 `verified`**，期望结论只能是 **`lead`**，并必须显式声明限制。

用例用于在 Agent 扩展问题类型之前，先检验其是否能：

1. 识别「查询本身不复杂、缺索引也不是根因，但翻页越深越慢」这一深分页特征；
2. 给出正确的定位（`LIMIT offset, size` 的调用点）；
3. 如实声明「无法证实为 `verified`」及原因（等待 Agent 支持新问题类型），而非勉强下结论或误报 `false_verified`。

## 目录结构

```text
case-08-deep-pagination-large-offset/
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
| `d1` | primary | `deep_offset` | `.../mapper/OrderMapper.java:16` | `lead` | `findOrdersByPage` 使用 `LIMIT #{offset}, #{size}`；深页须扫描并丢弃近 20 万行，代价随 offset 线性增长；`orders` 已有 `idx_orders_created_at`，缺索引并非根因 |
| `d2` | decoy | `redundant_count` | `.../mapper/OrderMapper.java:20` | `unclassified` | `pageOrders` 每次额外执行 `SELECT COUNT(*)` 求总数；对所有页成本恒定，无法解释「深页明显慢于首页」，属干扰项 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `lock_contention` / `network_latency`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单）
mvn spring-boot:run

# 3. 触发症状（深页）
curl "http://localhost:8080/api/orders/page?page=10000&size=20"

# 4. 对照首页（应明显更快）
curl "http://localhost:8080/api/orders/page?page=1&size=20"
```

## 评估要点

- 关键观察：同一接口下，深页耗时随 `offset` 增大而近似线性增长；首页与深页差距显著；`size` 与总行数不变时差异只来自 `offset`。
- 可证实性：**无法**由常规「补索引单变量实验」证实（`orders` 已具备 `idx_orders_created_at`）；只能以「深浅页耗时随 offset 变化」佐证，故期望 `lead` 而非 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条，含「等待 Agent 支持」）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。
- **待支持标注**：当前 `ProblemKind` 不含 `deep_pagination`，本用例归档为「等待 Agent 支持」；待 Agent 扩展问题类型后，可重判为 `normal`（若届时能由深浅页对照证据闭环）。

## 与其它用例的关系

- 与 `case-07-n-plus-one-order-user` 同属「问题类型待 Agent 支持」的预置用例，均为 `boundary / lead`：
  - `case-07` 的开销来自**调用次数放大**（1+size 次往返）；
  - 本用例的开销来自**单条查询内部按 offset 的无效扫描**。
- 与 `slow_query` 系用例的区别：本用例无法用「补索引」证实（索引已存在），这正是其被定为 `boundary` 的原因；用于验证 Agent 是否会因「有慢查询症状」而误开「缺索引」处方（`false_verified`）。
