# case-26-n-plus-one-category-count-loop

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `n_plus_one` |
| `difficulty` | `medium` |
| 期望结论 | `lead` |
| 来源 | 改编自 [tailwind8/portfolio-reserve](https://github.com/tailwind8/portfolio-reserve) Issue #68（`source=adapted`，许可证待核验） |

设计意图：后台统计接口在拿到全部分类后，**对每个分类逐条执行 `COUNT` 与 `SUM`**，形成 `2N+1` 次数据库往返。单条聚合按 `idx_orders_category` 走索引、执行计划本身无问题，缺陷在于**调用次数随分类数线性增长**。用例考察 Agent 是否能：

1. 把根因定位到「循环中的逐条查询」（N+1），而非任何单条 SQL 的执行计划；
2. 认识到当前 Agent 的 `ProblemKind` 仅支持 `slow_query`，`n_plus_one` 在问题类型扩展前**不可能产出 `verified`**，只能给出 `lead`（等待 Agent 支持）；
3. 不虚构不存在的索引类根因（避免 `false_verified`）。

## 上游来源与原汁原味的保留

- 上游：`tailwind8/portfolio-reserve` Issue #68。
- 上游版本：`main@b3bfbf5228c276ba696dd78ff84fed5741a80d33`。
- 保留的原汁原味：上游为 Next.js API 路由 `src/app/api/admin/stats/route.ts`（129-142 行）在 `for` 循环内逐分类调用 Prisma `count`，查询数由 100 增至 101。
- 按数据集约定的改造：技术栈统一为 Java 17 + Spring Boot 3.2.5 + MyBatis 3.0.3 + MySQL 8.0；保留「先取分类列表，再在循环中逐分类聚合」的 N+1 语义，并扩展为 `COUNT` 与 `SUM` 两趟循环（`2N+1`）。上游许可证尚未核验，`provenance.license` 标注为「待核验」，不臆断。

## 目录结构

```text
case-26-n-plus-one-category-count-loop/
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
| `d1` | primary | `n_plus_one` | `.../service/OrderStatsService.java:26` | `lead` | `buildStats` 先取去重分类（1 次）再逐分类 `countByCategory`（N 次）；单条 COUNT 走 `idx_orders_category`，问题在于调用次数 |
| `d2` | secondary | `n_plus_one` | `.../service/OrderStatsService.java:30` | `lead` | 第二个循环逐分类 `sumAmountByCategory`，与 d1 同源，合计 `2N+1`；primary 仍定位在 `countByCategory` 循环 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `jvm_gc_pause`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单 / 100 分类）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/admin/stats"
```

## 评估要点

- `decision_match = under`（期望 `lead`，Agent 不得给出 `verified`）。
- `root_cause_recall`：命中 `d1` 即视为召回主根因；`d2` 属同源次要。
- `false_verified = false`：Agent 若宣称 `verified`（例如声称「已加索引证实」）即判失败。
- `limitation_declared`：须命中 `case.json` 中 `expected.limitations_required` 的 3 条声明（含「等待 Agent 支持 N+1」）。
- `reward_profile = boundary_composite`，`timeout_seconds = 2400`。
- 该缺陷**无法**由平台单变量索引实验证实，故整体期望 `lead`。

## 与其它用例的关系

- 与 `case-16-n-plus-one-stop-times-hotpath` 同为 `n_plus_one` / boundary / `lead`，但场景不同：`case-16` 是「行程热路径逐条查 StopTimes」，本用例是「后台统计逐分类聚合」。
- 与 `case-07-n-plus-one-order-user`（`n_plus_one`）互为正交样本，覆盖「循环内逐条聚合」这一入口。
