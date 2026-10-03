# case-02-slow-query-composite

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `slow_query` |
| `difficulty` | `hard` |
| 期望结论 | `lead`（主缺陷可证实，整体因组合缺陷与契约限制不能判 `verified`） |

设计意图：项目**同时存在多个真实性能缺陷**，且其中若干缺陷（前导通配符、深分页、COUNT）无法通过平台唯一允许的单变量（`variable="index"`）实验证实。用例考察 Agent 是否：

1. 能识别出**可被单变量索引实验证实**的主缺陷并给出证据；
2. 对其余缺陷**只给 lead 而非强行 verified**（不得制造 false verified）；
3. 显式声明 `limitations`（声明未证实的次要缺陷与结论的适用范围）；
4. 主动排除干扰解释（锁竞争 / 网络 / GC）。

## 目录结构

```text
case-02-slow-query-composite/
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
| `d1` | primary | `missing_composite_index` | `.../mapper/OrderMapper.java:21` | `verified` | `orders` 缺 `(status, created_at)` 复合索引 → `Using filesort`；加索引即可由单变量实验证实 |
| `d2` | secondary | `full_table_scan` | `.../mapper/OrderMapper.java:19` | `lead` | `users.email` 前导通配符 `LIKE '%x%'`，索引失效；修复需改写查询而非加索引 |
| `d3` | secondary | `n_plus_one` | `.../service/OrderService.java:29` | `lead` | 每条订单各查一次用户；`ProblemKind` 暂不支持 `n_plus_one` |
| `d4` | secondary | `redundant_count` | `.../mapper/OrderMapper.java:30` | `lead` | 每次请求执行同构 `COUNT(*)` |
| `d5` | secondary | `deep_offset` | `.../mapper/OrderMapper.java:22` | `lead` | `LIMIT offset, size` 大偏移量低效 |
| `d6` | decoy | `select_star` | `.../mapper/OrderMapper.java:15` | `unclassified` | `SELECT o.*`，影响轻微，**不应被判为根因** |

期望命中根因：`d1`。期望排除的解释：`lock_contention` / `network_latency` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 5 万用户 / 20 万订单）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/orders/search?email=user1&status=PAID&page=1&size=20"
```

## 评估要点

- 单变量实验：`baseline` 对照 `candidate_index`（为 `orders` 加 `(status, created_at)` 复合索引），
  重复 ≥ 3 次、相对波动 ≤ 25%、耗时差 ≥ 1ms（`MeasurementPolicy`）。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- **硬门禁**：本用例 `no_false_verified` —— 任何对 `d2/d3/d4/d5/d6` 的 `verified` 结论都判不合格。
- 未声明 `limitations` 判不合格。

## 与《数据集结构规范》的对照

本用例是规范中「组合缺陷项目应作为 `boundary` 归档」的落地实例：主缺陷 `primary`，
其余 `secondary`/`decoy`，并在 `expected` 中说明判定顺序与预期结论。
