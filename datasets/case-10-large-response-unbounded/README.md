# case-10-large-response-unbounded

> **维护者文档（含答案，不得暴露给被测 Agent）**
> 评估运行时只暴露 `project/`，本文件、`case.json` 与 `docs/` 均须隔离。

## 用例定位

| 项 | 值 |
| --- | --- |
| `case_type` | `boundary`（边界用例） |
| `problem_kind` | `large_response` |
| `difficulty` | `medium` |
| 期望结论 | `lead`（并显式声明限制；**等待 Agent 支持**） |

设计意图：项目存在**一个真实、机制明确的结构性缺陷**——`GET /api/orders/all` 经 `OrderService.listAll()` → `OrderMapper.findAllOrders()` **无分页**地 `SELECT *` 取回全表约 20 万行，并**逐行序列化含 `remark`（约 200 字符）的完整实体**，单次响应体达数十 MB。真正的开销在**结果序列化与网络传输**，而不在 SQL 执行计划本身。

与 `slow_query` 系用例不同，本用例的缺陷**不是靠执行计划**体现的：全表扫描无 `WHERE`、无 `ORDER BY`，计划本身毫无问题，加索引也不会改变返回量。真正的成本是「把全表塞进一个响应体」的序列化与传输。理想情况下可由「响应字节数 / 返回行数随全表规模增长」证实，但当前 Agent 的 `ProblemKind` 仅支持 `slow_query`（且 `Finding.verified_requires_structural_evidence` 要求 `kind == "slow_query"`），因此**在本用例上不可能产出 `verified`**，期望结论只能是 **`lead`**，并必须显式声明限制。

用例用于在 Agent 扩展问题类型之前，先检验其是否能：

1. 识别「响应体过大」这一**非 SQL 计划层**的问题特征；
2. 给出正确的定位（无分页的查询方法）；
3. 如实声明「无法证实为 `verified`」及原因（等待 Agent 支持新问题类型），而非勉强下结论或误报 `false_verified`。

## 目录结构

```text
case-10-large-response-unbounded/
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
| `d1` | primary | `unbounded_response` | `.../mapper/OrderMapper.java:24` | `lead` | `findAllOrders` 无分页地 `SELECT *` 返回全表约 20 万行，并逐行序列化含 `remark` 大字段的完整实体，单次响应体达数十 MB；瓶颈在序列化与网络传输，而非 SQL 计划本身 |

期望命中根因：`d1`。期望排除的解释：`missing_index` / `slow_query` / `n_plus_one` / `connection_pool`。

## 运行方式

```bash
# 1. 启动 MySQL（3306）
cd project && docker compose up -d mysql

# 2. 启动应用（自动生成 20 万订单，每条 remark 约 200 字符）
mvn spring-boot:run

# 3. 触发症状
curl "http://localhost:8080/api/orders/all"
```

## 评估要点

- 关键观察：单次请求耗时高且响应体巨大（数十 MB），耗时与返回行数 / 响应字节数近似正相关；数据量越大越明显。
- 可证实性：**无法**由单变量索引实验证实（全表 `SELECT *` 无 `WHERE` / `ORDER BY`，计划本身无问题，补索引也不改变返回量），故期望 `lead` 而非 `verified`。
- 使用 `evaluation.checks` 中的检查项判定，`reward_profile = boundary_composite`。
- 边界判定：期望 `decision_match = under`（`lead`），`false_verified = false`；
  `limitation_declared = true`（须覆盖 `limitations_required` 的 3 条，含「等待 Agent 支持」）。
- 若 Agent 强行给出 `verified`，触发 `false_verified` 硬闸门 → 总分为 0，按「误判」单独统计。
- **待支持标注**：当前 `ProblemKind` 不含 `large_response`，本用例归档为「等待 Agent 支持」；待 Agent 扩展问题类型、并支持以响应字节数 / 返回行数等证据闭环后，可重判为 `normal`。

## 与其它用例的关系

- 与 `case-08-deep-pagination-large-offset`（`deep_pagination`）同属「大结果集 / 大响应」谱系：`case-08` 关注深分页 `offset` 的扫描代价，本用例关注**无分页地返回全表**导致的响应体过大（序列化 / 传输代价）。
- 与 `case-07-n-plus-one-order-user` 同属「问题类型待 Agent 支持」的预置用例，均为 `boundary / lead`。
- 与 `slow_query` 系用例的区别：本用例的耗时**不体现在执行计划**上（无 `WHERE` / `ORDER BY` 的全表扫描计划本身无问题），不能用单变量索引实验证实，正是其被定为 `boundary` 的原因。
