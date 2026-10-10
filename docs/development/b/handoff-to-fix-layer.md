# B → 修复层：数据交接格式

日期：2026-10-10。

本文固化 N+1 查询诊断（问题二）诊断层与**问题修复层**之间的结构化数据交接格式。
它是 [N+1 诊断设计文档 §5](../../superpowers/specs/2026-10-10-n-plus-one-diagnosis-design.md)
的落地契约，随代码实现同步维护；实现以 [models/n_plus_one.py](../../../src/project_doctor/models/n_plus_one.py)
与 [models/finding.py](../../../src/project_doctor/models/finding.py) 为准。

## 1. 交接方向

| 方向 | 内容 | 载体 |
|---|---|---|
| 诊断 → 修复层 | 可复现的结构化修复目标（永久代码改写） | `Finding` + `Recommendation` + `fix_spec`（`BatchQuerySpec`） |
| 修复层 → 诊断层 | 复测回填验证结果 | 回填 `Recommendation.validation_status` / `measured_gain_percent` / `retest_experiment_ids` |

核心原则：诊断层**不靠自由文本**交接，修复层**确定性消费**结构化字段；反过来，修复层**不回写诊断判据**，只回填复测结果。

## 2. 交接体 = `Finding` + `Recommendation` + `fix_spec`

`Finding` 上新增可选字段 `fix_spec: BatchQuerySpec | None`。N+1 结论的完整交接体由三部分构成：

- `Finding`：诊断结论（kind / status / 证据 / 影响）。
- `Recommendation`：修复动作与机制（可读 + 可枚举）。
- `fix_spec`：`BatchQuerySpec`，修复层据此确定性改写的结构化目标。

慢查询（`slow_query`）沿用其既有的 `Recommendation`（`mechanism="index_access_cost"`），
`fix_spec` 为 `None`——本文只规范 N+1 的 `fix_spec` 交接。

## 3. `BatchQuerySpec`（`models/n_plus_one.py`）

```python
FixStrategy = Literal["batch_in", "joinedload", "selectinload"]

class BatchQuerySpec(Contract):
    kind: Literal["n_plus_one"] = "n_plus_one"
    strategy: FixStrategy
    child_template: Identifier          # 参数化子查询模板，如 "SELECT * FROM users WHERE id = ?"
    key_column: Identifier              # 子查询关联键（来自父结果集），如 "id"
    child_code_location: CodeLocation   # 子查询的 SQL 定义位置（mapper 方法）
    observed_child_count: NonNegativeInt
    parent_sql_call_ids: list[Identifier] = Field(default_factory=list)
```

| 字段 | 语义 | 约束 |
|---|---|---|
| `kind` | 固定 `n_plus_one`，与 `Finding.kind` 一致 | 校验器强制相等 |
| `strategy` | 修复机制，枚举 `batch_in` / `joinedload` / `selectinload` | 未知值拒绝 |
| `child_template` | 参数化子查询模板（字面量归为 `?`） | 由 `parameterize_sql` 或 `SqlCall.template_sql` 得到 |
| `key_column` | 子查询关联键，来自父结果集 | 由模板 `WHERE <col> = ?` 提取 |
| `child_code_location` | 子查询 SQL 定义位置（mapper 方法） | 来自 `SqlCall.code_location`，提交/路径/行可核验 |
| `observed_child_count` | 基线每请求实测子查询次数上限 | 与父 `rows_returned` 计数相关 |
| `parent_sql_call_ids` | 父查询 `SqlCall.id` 列表 | 供修复层回溯父结果集 |

## 4. 完整交接 JSON 示例

```json
{
  "id": "finding-<sha20>",
  "task_id": "<task-id>",
  "kind": "n_plus_one",
  "status": "verified",
  "scenario_id": "n-plus-one-orders-search",
  "experiment_ids": ["<experiment-id>"],
  "sql_call_ids": ["sql-<req>-child-1", "sql-<req>-child-2", "..."],
  "code_locations": [
    { "commit": "<commit>", "path": "src/main/java/com/example/slowquery/mapper/OrderMapper.java", "line": 40 }
  ],
  "evidence_refs": ["<artifact-id>", "..."],
  "excluded_explanations": ["<已排除解释>"],
  "impact": {
    "method": "intervention",
    "latency_delta_ms": 90.0,
    "affected_request_ids": ["<req>", "..."],
    "shared_sql_call_ids": ["sql-<req>-child-1", "..."],
    "uncertainty": ["本次单变量批量干预，仅证明调用次数相关的耗时变化。"]
  },
  "recommendation": {
    "action": "把循环内的逐条查询改为一次 WHERE id IN (...) 批量查询，消除随列表条数线性增长的数据库往返",
    "mechanism": "batch_in",
    "conditions": ["子查询关联键列为 id", "父结果集大小与子查询次数相关，须确认去重与返回顺序"],
    "costs": ["IN 列表过长需分批", "需保持业务结果的去重与顺序"],
    "validation_status": "expected_mechanism",
    "measured_gain_percent": null
  },
  "fix_spec": {
    "kind": "n_plus_one",
    "strategy": "batch_in",
    "child_template": "SELECT * FROM users WHERE id = ?",
    "key_column": "id",
    "child_code_location": {
      "commit": "<commit>",
      "path": "src/main/java/com/example/slowquery/mapper/OrderMapper.java",
      "line": 40
    },
    "observed_child_count": 20,
    "parent_sql_call_ids": ["sql-<req>-parent"]
  },
  "limitations": ["..."]
}
```

### 代码位置语义（诚实边界）

`Finding.code_locations` 与 `fix_spec.child_code_location` 都取**子查询的 SQL 定义位置**
（mapper 方法，如上例 `OrderMapper.java:40`），因为诊断层只能从 `SqlCall.code_location`
确知这一点。触发循环/懒加载的 **Java 调用代码行**（如 `OrderService.java:28` 的 `for` 循环）
诊断层不直接给出，而由修复层按 mapper 方法**回溯**得到；该限制记录为一条 `limitation`：
「循环调用代码位置取子查询的 SQL 定义位置（mapper 方法）；Java 循环代码行需修复层按该方法回溯。」

## 5. 机制枚举与校验器

`FixStrategy` 枚举限定 `strategy`；`Recommendation.mechanism` 因与慢查询共用，类型仍是自由
`Identifier`，因此 N+1 的机制一致性由两条校验器联合保证（见 [models/finding.py](../../../src/project_doctor/models/finding.py)）：

- `fix_spec_matches_kind_and_mechanism`：`fix_spec.kind == Finding.kind`，且
  `Recommendation.mechanism == fix_spec.strategy`。
- `verified_requires_structural_evidence`：`verified` 必须同时具备 `experiment_ids`、
  `sql_call_ids`、`code_locations`、`evidence_refs`、`excluded_explanations`、`recommendation`，
  且 `kind ∈ {slow_query, n_plus_one}`。

即：修复层可只依赖 `fix_spec.strategy`（枚举）确定性改写；`Recommendation.mechanism` 与之一致
是硬校验，不会出现「文本说 joinedload、结构化说 batch_in」的撕裂。

## 6. 临时干预 vs 永久改写

| | `QueryShapeRecipe`（§4.1） | `BatchQuerySpec`（本文） |
|---|---|---|
| 用途 | 实验运行时**临时、可逆**地切换查询形状，证明机制 | 交给修复层做**永久代码改写** |
| 消费者 | 实验运行时（A 侧） | 问题修复层 |
| 载体 | `features/experiments/interventions.py` | `models/n_plus_one.py` |

二者字段同名（`strategy` / `child_template` / `key_column`），但**不是**同一对象：
配方用运行时开关（`flag` + 两个取值）翻转，`fix_spec` 描述最终要改写的代码目标。

## 7. 修复层 → 诊断层（复测回填）

修复层按 `fix_spec` 改写 → 重跑正确性 + 基准负载 → 只回填 `Recommendation` 的复测字段：

```json
{
  "recommendation": {
    "validation_status": "retested",
    "measured_gain_percent": 42.5,
    "retest_experiment_ids": ["<retest-experiment-id>"]
  },
  "impact": { "method": "intervention", "latency_delta_ms": 12.3 }
}
```

- `Recommendation.validation_status` 由 `expected_mechanism`（未复测）→ `retested`；
- `measured_gain_percent` 与 `retest_experiment_ids` 只在复测后允许非空（模型校验器强制）；
- 逐值子集证明（子参数确实来自父结果集键）在复测时由修复层重跑父查询补齐——诊断层只证明
  **计数相关**，不声称逐值子集（见设计 §2.2(3) 的诚实边界）。

## 8. 交接不变量

- 诊断层**只产出** `validation_status="expected_mechanism"` 且 `measured_gain_percent=null` 的交接体，不声称已测收益。
- 修复层**不能改写**诊断判据、测试数据或通过标准；只能回填复测三字段。
- 交接体与 `Finding.evidence_refs` / `sql_call_ids` 可追溯：修复层复测对照必须引用同一场景、数据快照与提交。
- `fix_spec` 为 `None` 时（`key_column` 无法提取或结论为 `unclassified`）不构成结构化交接，修复层不得凭自由文本改写。
