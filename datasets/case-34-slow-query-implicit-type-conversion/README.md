# case-34-slow-query-implicit-type-conversion

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `slow_query` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自 MySQL「字符串列与数值比较触发隐式类型转换 → 既有索引失效」的公开文档与社区案例（`source=adapted`，许可证待核验） |

设计意图：项目**只有一个真实性能缺陷**——`members.member_no` 是 `VARCHAR(32)` 且已建索引，但查询以 `long` 参数绑定，MySQL 为完成比较把该列整列隐式转换为数值，既有索引因此失效，退化为全表扫描。该缺陷可定位、可用 EXPLAIN 取证，但修复方式是改参数类型（或显式字符串语义）而非补索引，无法由平台唯一允许的单变量（`variable="index"`）实验稳定证实。用例考察 Agent 是否能：

1. 借助 EXPLAIN（`type=ALL` / `key=NULL`，索引存在却未被使用）判定「索引因类型转换失效」；
2. 区分「缺索引」与「索引存在但被隐式转换弃用」两类不同根因；
3. 显式声明边界限制（非补索引可解、结论依赖类型转换规则）。

## 上游来源与原汁原味的保留

- 上游：MySQL 的类型转换规则（字符串列与数值比较时把整列转为数值比较）——见官方文档《Type Conversion in Expression Evaluation》及大量社区报告。
- 保留的原汁原味：字符串列存数字形态、以数值参数比较 → 列被隐式转换 → 索引不可用 → 全表扫描，这是 MySQL 原生可复现的行为。
- 按数据集约定的改造：技术栈统一为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；判分指标统一为可实测字段 `duration_ms`；数据规模收敛到 30 万会员以保证可复现与观测窗口可控。

## 目录结构

```text
case-34-slow-query-implicit-type-conversion/
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
| `d1` | primary | `implicit_type_conversion_index_drop` | `.../mapper/MemberMapper.java:12` | `lead` | `members.member_no` 为 `VARCHAR(32)` 且已建索引；查询以 `long` 参数绑定（JDBC 发送 BIGINT）→ MySQL 把列隐式转为数值 → 索引失效 → `ALL members` |

期望命中根因：`d1`。期望排除的解释：`lock_contention` / `network_latency` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 30 万会员）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/members/by-no?memberNo=100000001"
```

## 评估要点

- 单变量实验：`baseline` 对照 `candidate_index`（为 `member_no` 建索引，索引其实已存在），
  重复 ≥ 3 次、相对波动 ≤ 25%、耗时差 ≥ 1ms（`MeasurementPolicy`）。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界用例考察「显式声明限制」：Agent 须说明该形态为参数类型不匹配导致的隐式转换、修复是改参数类型而非补索引，并给出 EXPLAIN 证据。
- 若 Agent 强行给出 `verified`，`false_verified = false` 不通过。

## 与其它用例的关系

- 与 `case-33-slow-query-or-cross-column` 同属「既有索引因谓词形态失效」，但机制不同：`case-33` 是跨列 OR 使 `index_merge` 不可用，本用例是**参数类型与列类型不匹配触发隐式类型转换**。
- 与 `case-24-slow-query-audit-log-scan-sort`（缺复合索引，期望 `verified`）不同：本用例索引**已存在**，问题在于参数类型，故期望 `lead`。
