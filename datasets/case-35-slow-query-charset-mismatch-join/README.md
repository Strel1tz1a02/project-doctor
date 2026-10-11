# case-35-slow-query-charset-mismatch-join

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `slow_query` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自 MySQL「JOIN 两侧连接列字符集不一致（utf8mb3 与 utf8mb4）导致被转换列索引失效」的公开文档与社区案例（`source=adapted`，许可证待核验） |

设计意图：项目**只有一个真实性能缺陷**——`authors.author_code`（utf8mb4）与 `articles.author_code`（旧表 utf8mb3）字符集不一致，连接比较需要先把 utf8mb3 一侧转换，`articles.author_code` 上的 `idx_articles_author_code` 因此无法用于该连接比较，优化器把 `articles` 退化为全表扫描。该缺陷可定位、可用 EXPLAIN 取证，但修复方式是统一两侧字符集/排序规则而非补索引，无法由平台唯一允许的单变量（`variable="index"`）实验稳定证实。用例考察 Agent 是否能：

1. 借助 EXPLAIN（`articles` 为 `type=ALL` / `key=NULL`，索引存在却未被使用）判定「索引因字符集不一致失效」；
2. 区分「缺索引」「类型转换失效」与「字符集/排序规则不一致导致索引不可用」三类根因；
3. 显式声明边界限制（非补索引可解、结论依赖两侧列定义）。

## 上游来源与原汁原味的保留

- 上游：MySQL 在比较两个不同字符集/排序规则的列时，需按 coercibility 规则转换其中一侧；被转换列上的 B-tree 索引无法用于该比较——见官方文档《Collation Coercibility in Expressions》与大量社区排障记录（如「utf8mb3 与 utf8mb4 表 JOIN 索引失效」）。
- 保留的原汁原味：历史表用 utf8mb3、新表用 utf8mb4、两表通过同一业务键连接 → 连接列字符集不一致 → 被转换侧索引失效 → 全表扫描，这是 MySQL 原生可复现的行为。
- 按数据集约定的改造：技术栈统一为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；判分指标统一为可实测字段 `duration_ms`；数据规模收敛到 30 万文章 / 5 万作者以保证可复现与观测窗口可控。

## 目录结构

```text
case-35-slow-query-charset-mismatch-join/
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
| `d1` | primary | `charset_mismatch_join_index_drop` | `.../mapper/ArticleMapper.java:14` | `lead` | `authors.author_code`（utf8mb4）与 `articles.author_code`（utf8mb3）字符集不一致 → 连接比较需转换 `articles` 侧 → `idx_articles_author_code` 失效 → `ALL articles` |

期望命中根因：`d1`。期望排除的解释：`lock_contention` / `network_latency` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 30 万文章 / 5 万作者）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/articles/by-author?authorCode=A000012"
```

## 评估要点

- 单变量实验：`baseline` 对照 `candidate_index`（为 `author_code` 建索引，两侧索引其实已存在），
  重复 ≥ 3 次、相对波动 ≤ 25%、耗时差 ≥ 1ms（`MeasurementPolicy`）。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界用例考察「显式声明限制」：Agent 须说明该形态为连接列字符集不一致导致被转换侧索引失效、修复是统一字符集而非补索引，并给出 EXPLAIN 证据。
- 若 Agent 强行给出 `verified`，`false_verified = false` 不通过。

## 与其它用例的关系

- 与 `case-33-slow-query-or-cross-column`（跨列 OR 使 `index_merge` 不可用）、`case-34-slow-query-implicit-type-conversion`（参数类型与列类型不匹配触发隐式转换）同属「既有索引因谓词/比较形态失效」，但本用例的失效来自**两侧连接列字符集（排序规则）不一致**。
- 与 `case-24-slow-query-audit-log-scan-sort`（缺复合索引，期望 `verified`）不同：本用例索引**已存在**，问题在于连接列的字符集定义，故期望 `lead`。
