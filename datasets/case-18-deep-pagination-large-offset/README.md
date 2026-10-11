# case-18-deep-pagination-large-offset

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例：问题类型尚未被 Agent 支持，只能给 `lead`） |
| `problem_kind` | `deep_pagination` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自 [pymc-labs/decision-hub](https://github.com/pymc-labs/decision-hub) Issue #56（MIT，`source=adapted`） |

设计意图：`GET /api/items/page` 以 `LIMIT #{limit} OFFSET #{offset}` 分页，偏移越大越慢。用例考察 Agent 是否能：

1. 识别「查询代价随位移深度（OFFSET）线性增长」——而非任何缺索引或单条 SQL 执行计划问题；
2. 在问题类型尚未被 Agent 支持时，给出 `lead` 结论并**显式声明限制**（不得为了拿分伪造 `verified`）；
3. 不把恒定成本的干扰项（d2：每次请求 `SELECT COUNT(*)` 求总数）误判为根因。

## 上游来源与原汁原味的保留

- 上游（许可来源）：`pymc-labs/decision-hub` Issue #56（**MIT**，`won't fix`）——`database.py` 1396–1399 使用 `base.limit(limit).offset(offset)`，`OFFSET 170000`。
- 原候选（**未采用**）：`zbnerd/probabilistic-valuation-engine` Issue #233（closed，P1）《[P1][Nightmare-18] Deep Paging 성능 개선 - Cursor-based Pagination 도입》——深分页查询形如 `SELECT * FROM items ORDER BY id LIMIT 10 OFFSET 1000000`，OFFSET 增大后延迟由约 1ms 退化至约 5000ms；**该仓库根目录无任何 LICENSE**，故不作为落盘来源，仅作为同一 `deep_offset` 机制的佐证记录于此。
- 保留的原汁原味：
  - `limit(limit).offset(offset)` 的 `LIMIT ... OFFSET ...` 分页语义逐字迁移到 `ItemMapper.findItemsByOffset(@Param("limit") int limit, @Param("offset") int offset)`；
  - 表名 `items` 与 `ORDER BY id` 的排序语义保持不变；
  - 深层 OFFSET（170000）取自上游 #56 的可复现数值。
- 按数据集约定的改造：上游为 Python + SQLAlchemy，本项目按统一骨架改写为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；判分指标统一为可实测字段 `duration_ms`；数据规模按数据集约定设定为 `items=1200000`（≥100 万行）以保证深位移退化稳定可测。

## 目录结构

```text
case-18-deep-pagination-large-offset/
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
| `d1` | primary | `deep_offset` | `src/main/java/com/example/slowquery/mapper/ItemMapper.java:16` | `lead` | `findItemsByOffset` 使用 `LIMIT #{limit} OFFSET #{offset}`，深位移时 offset 接近全表行数，MySQL 须沿主键顺序扫描并丢弃前 offset 行；`items` 已具备 `idx_items_created_at`，缺索引并非根因 |
| `d2` | decoy | `redundant_count` | `src/main/java/com/example/slowquery/mapper/ItemMapper.java:20` | `unclassified` | `countItems` 每次请求额外 `SELECT COUNT(*)`，成本对首页/深页恒定，无法解释深位移显著变慢，属干扰项 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `lock_contention` / `network_latency`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 120 万 items）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/items/page?offset=170000&limit=20"
```

## 评估要点

- 边界用例（问题类型 `deep_pagination`，等待 Agent 支持）：本用例**不可由单变量实验证实**——`items` 已具备 `idx_items_created_at`，缺索引不是根因，耗时来自「扫描并丢弃 offset 行」；且当前 Agent 的 `ProblemKind` 仅支持 `slow_query`、`Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`，故在本用例上不可能产出 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- `decision_match`：期望 `lead`（Agent 若给出 `verified` 即触发 `false_verified` 硬闸门）。
- `limitation_declared`：必须声明三条 `expected.limitations_required`（判定依据、问题类型未支持、依赖位移深度）。
- `false_verified` 硬闸门：任何为大 OFFSET 深分页伪造 `verified` 的输出直接判负。
- **待支持标注**：等待 Agent 支持 `deep_pagination` 问题类型；届时本用例可升级为 `normal`。

## 与其它用例的关系

- 与 `case-08` 同属「大 OFFSET 深分页」家族，机制标签均为 `deep_offset`：`case-08` 为手工构造（`orders` 表、200k 行、`page=10000`），本用例为真实项目改编（`items` 表、1.2M 行、`offset=170000`），二者共享统一骨架便于对照。
- 与 `case-15` / `case-04` 对照：后两者是 `slow_query`（缺索引 → 全表扫描）、`decision=verified`；本用例是「索引已具备、代价来自 OFFSET 丢弃行」，用于区分「缺索引」与「深分页」。
- 与 `case-08` 一致，本用例显式提供 `decoy`（d2）以检验 Agent 是否能把主根因收敛到唯一 `primary`。
