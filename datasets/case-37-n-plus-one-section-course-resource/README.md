# case-37-n-plus-one-section-course-resource

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `n_plus_one` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自常见的「课程章节列表逐条回查课程标题 + 逐条统计资源数」N+1 场景（`source=adapted`，许可证待核验） |

设计意图：课程章节列表接口在拿到最近章节列表后，**在第一个循环中对每个章节逐条回查所属课程标题**，并**在第二个循环中逐条统计每个章节的资源数**，形成 `2N+1` 次数据库往返。单条查询走主键 / 索引、执行计划本身无问题，缺陷在于**调用次数随列表页大小线性增长**。用例考察 Agent 是否能：

1. 把根因定位到「循环中的逐条回查」（N+1），而非任何单条 SQL 的执行计划；
2. 认识到 `n_plus_one` 现虽由 Agent 的 `ProblemKind` 支持，但本用例未纳入「逐条 vs 批量」判别实验与批量改造后复测增益等结构化证据，故维持 `lead`；
3. 不虚构不存在的索引类根因（避免 `false_verified`）。

## 上游来源与原汁原味的保留

- 上游：常见的「课程 / 目录章节列表逐条回查所属课程标题并逐条统计关联资源数」实现（许可证待核验，不臆断具体仓库与提交）。
- 保留的原汁原味：列表查询返回 N 条记录后，在循环中逐条发起父实体回查与子实体聚合，使数据库往返随 N 线性增长。
- 按数据集约定的改造：技术栈统一为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；把课程维度规整为 `courses` 小表并逐条查询、把资源维度规整为 `resources` 表并逐条 `COUNT`，形成课程标题回查（N）+ 资源数统计（N）两趟循环（`2N+1`）。上游许可证尚未核验，`provenance.license` 标注为「待核验」。

## 目录结构

```text
case-37-n-plus-one-section-course-resource/
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
| `d1` | primary | `n_plus_one` | `.../service/SectionService.java:27` | `lead` | `buildSections` 先取最近章节（1 次）再逐条 `findCourseTitleById`（N 次）；单条走 `courses` 主键，问题在于调用次数 |
| `d2` | secondary | `n_plus_one` | `.../service/SectionService.java:31` | `lead` | 第二个循环逐条 `countResourcesBySectionId`，与 d1 同源，合计 `2N+1`；primary 仍定位在课程标题回查循环 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万章节 / 5000 课程 / 40 万资源）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/sections/recent?size=100"
```

## 评估要点

- `decision_match = exact`（期望 `lead`，Agent 不得给出 `verified`）。
- `root_cause_recall`：命中 `d1` 即视为召回主根因；`d2` 属同源次要。
- `false_verified = false`：Agent 若宣称 `verified`（例如声称「已加索引证实」）即判失败。
- `limitation_declared`：须命中 `case.json` 中 `expected.limitations_required` 的 3 条声明（判定依据、`n_plus_one` 已支持但证据不足维持 `lead`、依赖列表页大小）。
- `reward_profile = boundary_composite`，`timeout_seconds = 2400`。
- 该缺陷**不能**由平台单变量索引实验证实；本用例亦未纳入「逐条 vs 批量」判别实验与改造复测增益证据，故整体期望 `lead`。

## 与其它用例的关系

- 与 `case-26-n-plus-one-category-count-loop` 区分：`case-26` 是「后台报表对每个分类逐条 COUNT/SUM」（两趟均为聚合）；本用例是「课程章节列表回查父实体标题 + 统计子实体数量」，域与「父实体回查」入口不同。
- 与 `case-31` / `case-36` 同为「列表 + 关联回查」，但回查对象与域不同：`case-31` 为动态流回查作者 + 点赞，`case-36` 为商品回查分类 + 品牌，本用例为章节回查课程 + 资源。
