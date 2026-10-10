# N+1 查询诊断设计（v0.1）

> 状态：设计稿，待复核。本文规定「N+1 查询」（问题二）的诊断判据、数据合同，以及与问题修复层的
> 数据交接格式。沿用 [平台架构设计](2026-10-02-platform-architecture-design.md) 的五层职责，
> 复用慢查询诊断（[slow_query.py](../../../src/project_doctor/features/diagnosis/slow_query.py)）已建立的
> 三路分级、锁排除、波动门槛与证据引用原则。检测原理与因果链见
> [performance-agent-deepdive-02-n-plus-one.md](../../diagnosis/performance-agent-deepdive-02-n-plus-one.md)。

## 1. 目标与交付边界

- **首版交付**：在同一有效请求内**检测并证明 N+1 结构**，并通过**批量化干预实验**打通 `verified`——
  把循环单条查询改为 `WHERE key IN (...)`（或 JOIN / 批量加载），证明查询次数 N+1 → 1～2、
  延迟下降、业务结果一致、扫描量不变。
- **干预与修复分离**：实验干预是**临时、可逆的运行时开关**（见 §4），用于证明机制；
  诊断产出的 `BatchQuerySpec` 才是交给修复层做**永久代码改写**的结构化交接（见 §5）。
- **不宣称**：把「同构 SQL 出现多次」直接当 N+1（分页 / 重试 / 合法批处理同样产生同构 SQL）；
  把「单请求查询次数多」当作已定位根因（须绑定父/子关联与参数来源）。

## 2. 诊断判据（`check_n_plus_one`）

### 2.1 检测信号（提示性）

- 同一 `Observation`（同一 `request_id`）内，**参数化模板相同**的 `SqlCall` 数量 ≥ 2；
- 这些子查询共享同一 `code_location`（同一 mapper 方法 + 行）；
- 模板相同而字面参数互异 → 「循环内查询」的结构指纹。

模板不等于现有 `normalized_sql`：`normalized_sql` 是字面精确的（`WHERE id = 123` 与 `WHERE id = 456`
是两个模板）。N+1 需要**参数化模板** `template_sql`（字面值归一为 `?`），见 §3.2。

### 2.2 结构证明（门槛）

同时满足以下才从「提示」升为「证明」：

1. **结构**：单请求内 `query_count = 1（父） + N（子）`，N ≥ 2；N 条子查询共享同一
   `template_sql` 与 `code_location`，字面参数互异。
2. **计数相关**：子查询次数 N 与父查询返回行数（`rows_returned`，或分页 `size`）一致或近似——
   「N 个对象 → N 条关联查询」。
3. **参数来源**：从子查询字面值可提取 N 个互异的关联键值；父查询按该键返回结果集。
   *诚实边界*：平台只能拿到父查询的 `rows_returned` 计数，拿不到父结果集的具体键值，因此
   「子参数 ⊂ 父结果键」是**计数相关 + 结构指纹 + 代码位置**的合取证明，不伪造「逐值子集」证据；
   需要逐值子集证明时，由修复层以重跑父查询比对（见 §5.2）。
4. **排除干扰**：沿用慢查询的锁排除（`LOCK_TIME` 实测表/行锁 + MDL 残差）、波动门槛、
   业务结果一致与恢复校验；排除分页、重试、合法批处理（须绑定同一有效请求 + 父/子关联 + 参数来源）。

### 2.3 三路分级

| 结论 | 条件 | 说明 |
|---|---|---|
| `verified` | 批量化干预使 `query_count` 由 N+1 降到 1～2，且延迟下降过波动门槛、业务结果一致、扫描量不变 | 依赖批量干预实验（§4） |
| `unclassified` | 单请求 `query_count ≈ 1`，无同构重复；或子查询次数不随父结果大小增长 | N+1 在当前数据/代码下未复现 |
| `lead` | 检测到 N+1 结构但无批量干预实验证实收益；或证据不足（缺代码位置 / 参数来源 / 锁或波动未排除） | 强证据 + 结构化交接，克制下结论 |

### 2.4 与慢查询的边界（共存判别）

一条慢请求可以**同时**存在慢查询与 N+1（父查询全表扫 + 循环子查询）。两者用**各自独立**信号判定，
不二选一：

- 慢查询 → 单条 SQL `rows_examined ≫ rows_sent` + 索引干预降低扫描量；
- N+1 → 同构子查询重复 N 次 + 计数相关 + 循环代码位置。

修复顺序：先解决扫描量（慢查询），复测后仍有 N+1 结构再处理调用次数。慢查询判据中
「单请求同模板多次调用」的排除语句保留，但应改为按 `template_sql`（参数化）判定，避免把 N+1 的
字面异构子查询误判成慢查询的多模板噪声。

## 3. 数据合同变更

### 3.1 `ProblemKind`（`models/common.py`）

```python
ProblemKind = Literal["slow_query", "n_plus_one", "unclassified"]
```

### 3.2 SQL 参数化模板（`integrations/observation/sql_probe.py` + `models/observation.py`）

`normalize_sql` 保持不变（字面精确，慢查询与证据校验依赖）。新增 `parameterize_sql(sql_text) -> str`：
把字符串字面值、数值字面值与 `?` 占位统一归一，得到**形状模板**，落到 `SqlCall.template_sql`。

同时把子查询互异的关联键字面值提取为**参数来源证据**（`SqlCall.parameter_provenance` 或新字段
`literal_parameters: list[str]`），供 §2.2(3) 证明「N 个互异参数」与「计数相关」。

### 3.3 每请求查询次数（`models/observation.py`）

`query_count` 不从新计数器引入，直接由 `Observation.sql_calls` 的 `len()` 派生；诊断层按
`request_id` 分组统计。需要在采集层保证 `history_limit`（当前 64）足以容纳父 + N 子查询，
否则 N+1 被截断会漏检——把截断风险作为一条 `limitation` 记录，不静默降级。

### 3.4 结构化修复交接 `BatchQuerySpec`（新增 `models/n_plus_one.py`）

类比慢查询的 `IndexRecipe`（结构化 DDL 配方），N+1 的修复交接使用结构化 `BatchQuerySpec`，
使修复层可确定性消费，不靠自由文本推断。注意：它是**永久代码改写**的交接体，与 §4.1 的
**临时干预配方** `QueryShapeRecipe`（证明机制用）是两个概念——前者交给修复层，后者给实验运行时。

```python
class BatchQuerySpec(Contract):
    kind: Literal["n_plus_one"] = "n_plus_one"
    strategy: Literal["batch_in", "joinedload", "selectinload"]
    child_template: Identifier          # 参数化子查询模板，如 "SELECT * FROM users WHERE id = ?"
    key_column: Identifier              # 子查询关联键（来自父结果集），如 "id"
    child_code_location: CodeLocation   # 触发循环/懒加载的代码位置
    observed_child_count: NonNegativeInt
    parent_sql_call_ids: list[Identifier] = Field(default_factory=list)
```

### 3.5 校验器与路由去硬编码

- `models/finding.py` 的 `Finding.verified_requires_structural_evidence` 现硬编码 `kind != "slow_query"`，
  改为按 `ProblemKind` 白名单校验（`verified` 允许 `slow_query` 与 `n_plus_one`）。
- `workflows/tools.py` 的假设 `supported` 判定现硬编码 `kind == "slow_query" and explanation == "index_access_cost"`，
  扩展 N+1 的机制标识（`n_plus_one` + `explanation == "n_plus_one_batch"`）。

## 4. 批量化干预实验与实验变量泛化（打通 `verified`）

`verified` 需要一个「批量化」候选组。现有 `ExperimentSpec.variable` 是 `Literal["index"]`，
`ExperimentLevel` 是 `("baseline", "candidate_index")`。扩展为：

- `ExperimentSpec.variable: Literal["index", "query_shape"]`
- `ExperimentLevel: Literal["baseline", "candidate_index", "candidate_batch"]`
  （慢查询仍用 `candidate_index`；N+1 用 `candidate_batch`。）

### 4.1 干预配方 `QueryShapeRecipe`（临时、可逆）

与慢查询的 DDL `IndexRecipe` 对称，N+1 的干预配方也是**可逆的受控变更**——但不是数据库 DDL，
而是应用运行时开关：demo 的 `OrderService.searchSlow` 内置两条实现分支（`n1` 循环单查 /
`batch` 批量 `WHERE id IN (...)`），由配置开关切换。

```python
class QueryShapeRecipe(Contract):
    kind: Literal["query_shape"] = "query_shape"
    strategy: Literal["batch_in", "joinedload", "selectinload"]
    flag: Identifier                 # 应用开关，如 "app.query.mode"
    baseline_value: Identifier       # 如 "n1"
    candidate_value: Identifier      # 如 "batch"
    child_template: Identifier       # 参数化子查询模板
    key_column: Identifier           # 子查询关联键
    child_code_location: CodeLocation
```

运行时语义：`baseline` 组 = 开关为 `baseline_value`；`candidate_batch` 组 = 开关设为
`candidate_value` → 重跑 → 恢复开关为 `baseline_value`。对称可逆，与 `IndexRecipe` 的
`create_sql` / `drop_sql` 对齐。

*为何用开关而非源码补丁*：代码补丁 + 重建 + 恢复脆弱且难对称；开关切换是单变量、可逆、
不引入无关差异，也避免「把两个不同端点误当成同一路径的单变量对照」。具体开关载体（环境变量 /
配置表 / 启动参数）由 A 侧实现，契约只约束 `flag` + 两个取值。

### 4.2 `verified` 门槛

`candidate_batch` 组须同时满足，才 `verified`：

- 每请求 `query_count` 由 N+1 降到 1～2（子查询模板消失或只剩批量模板）；
- 请求延迟下降且过波动门槛（复用 `distinguishable`）；
- 业务结果一致（`result_digest` 两组相同）；
- 父查询扫描量不变（批量只消除调用次数，不改变父查询访问路径）。

### 4.3 对 A 侧的依赖

- demo：`OrderService` + `OrderMapper` 增加 `batch` 分支与开关读取；`DataInitRunner` 不变。
- 运行时：新增 `query_shape` 配方解析 + 开关应用/恢复 + 恢复校验（开关值回读 = `baseline_value`）。

## 5. 与问题修复层的数据交接格式

交接方向两条：诊断层 → 修复层（给出可复现的结构化修复目标），修复层 → 诊断层（复测回填验证结果）。

### 5.1 诊断 → 修复层

交接体 = `Finding(kind="n_plus_one")` + `Recommendation` + `fix_spec`（`BatchQuerySpec`）：

```json
{
  "finding_id": "finding-<sha>",
  "kind": "n_plus_one",
  "status": "lead",
  "scenario_id": "n-plus-one-orders-search",
  "code_locations": [
    { "commit": "<commit>", "path": "src/main/java/com/example/slowquery/service/OrderService.java", "line": 28 }
  ],
  "sql_call_ids": ["sql-<req>-0", "sql-<req>-1", "sql-<req>-2"],
  "recommendation": {
    "action": "把 OrderService.searchSlow 循环内的 findUserById 改为一次 WHERE id IN (...) 批量查询",
    "mechanism": "batch_in",
    "conditions": ["子查询键列为 users.id", "父结果集大小 = 分页 size", "确认去重与返回顺序"],
    "costs": ["IN 列表过长需分批", "需保持业务结果的去重与顺序"],
    "validation_status": "expected_mechanism"
  },
  "fix_spec": {
    "kind": "n_plus_one",
    "strategy": "batch_in",
    "child_template": "SELECT * FROM users WHERE id = ?",
    "key_column": "id",
    "child_code_location": { "commit": "<commit>", "path": "src/main/java/com/example/slowquery/mapper/OrderMapper.java", "line": 40 },
    "observed_child_count": 20,
    "parent_sql_call_ids": ["sql-<req>-parent"]
  }
}
```

字段语义约束：

| 字段 | 语义 | 约束 |
|---|---|---|
| `Finding.kind` | 诊断类型 | `n_plus_one` |
| `Finding.code_locations` | 触发循环/懒加载的代码位置 | 必须来自 `SqlCall.code_location`（提交/路径/行可核验） |
| `Recommendation.action/mechanism` | 修复动作与机制 | 机制限 `batch_in`/`joinedload`/`selectinload` |
| `Recommendation.validation_status` | 交接时必须是 `expected_mechanism`（未复测） | 复测后才可 `retested` |
| `fix_spec` | 结构化修复目标（`BatchQuerySpec`） | 修复层据此确定性改写，不靠自由文本 |

### 5.2 修复层 → 诊断层（复测回填）

修复层应用 `fix_spec` 改写 → 重跑正确性 + 基准负载 → 回填 `Recommendation`：

```json
{
  "recommendation": {
    "validation_status": "retested",
    "measured_gain_percent": 42.5,
    "retest_experiment_ids": ["exp-<retest>"]
  },
  "impact": { "method": "intervention", "latency_delta_ms": 12.3 }
}
```

- `Impact.method` 由 `unmeasured` → `intervention`（批量化确有延迟收益时）；
- 逐值子集证明（§2.2(3) 的诚实边界）在复测时补齐：修复层重跑父查询、比对子参数是否来自父结果集键。

### 5.3 交接不变量

- 诊断层**只产出** `expected_mechanism` 的交接体，不声称已测收益（`measured_gain_percent` 必须为 null）；
- 修复层**不能改写**诊断判据、测试数据或通过标准；复测结果只回填 `validation_status`/`measured_gain_percent`/`retest_experiment_ids`；
- 交接体与 `Finding.evidence_refs` / `sql_call_ids` 保持可追溯：修复层复测的对照必须引用同一场景、数据快照与提交。

## 6. 落点文件与职责

| 文件 | 改动 | 责任 |
|---|---|---|
| `models/common.py` | `ProblemKind` 加 `n_plus_one` | B |
| `models/n_plus_one.py`（新增） | `BatchQuerySpec`（修复交接） | B |
| `models/observation.py` | `SqlCall.template_sql` + `literal_parameters` | B |
| `models/finding.py` | `verified` 校验器去 `slow_query` 硬编码；`Recommendation` 机制枚举 | B |
| `models/experiment.py` | `ExperimentSpec.variable` 加 `query_shape`；`ExperimentLevel` 加 `candidate_batch` | B |
| `features/diagnosis/n_plus_one.py`（新增） | `check_n_plus_one`（§2 判据 + 三路分级） | B |
| `features/diagnosis/gates.py` | 复用锁/波动/恢复门槛；父/子分组助手 | B |
| `features/experiments/interventions.py` | `QueryShapeRecipe` + `parse_query_shape_recipe`（与 `IndexRecipe` 对称） | B 契约 |
| `integrations/observation/sql_probe.py` | `parameterize_sql` + 字面参数提取 | A |
| `workflows/diagnose.py` | 按 `ProblemKind` 分派 `check_slow_query` / `check_n_plus_one` | B |
| `workflows/tools.py` | 假设 `supported` 判定扩展 `n_plus_one` | B |
| `features/scenarios/discover.py` + `demo/reference/manifest.json` | 新增独立场景 `n-plus-one-orders-search` | B |
| `demo/slow-query-demo/` | `OrderService`/`OrderMapper` 加 `batch` 分支 + 开关读取 | A |
| A 运行时 | `query_shape` 配方应用/恢复 + 开关回读校验 | A |
| `features/reports/` | N+1 诊断卡（复用 `ReportData`，不重复计算影响） | B |

## 7. 测试与验证

**反例（不能升 `lead`/`verified`）**：

- 单请求 `query_count = 1`（无同构重复）→ `unclassified`；
- 同构子查询但跨请求（不同 `request_id`）→ 不构成 N+1；
- 同构子查询但无父/子关联（无父查询、或计数不相关）→ 仅提示，不证明；
- 缺代码位置 / 缺参数来源 / 锁或波动未排除 / 恢复未验证 → `lead`（证据不足）；
- 分页、重试、合法批处理产生的同构 SQL → 不被误判为 N+1。

**正例**：demo 的 `/api/orders/search`（`searchSlow` 循环 `findUserById`）→ 结构证明完整，产出
`lead` + `BatchQuerySpec`；若后续批量干预实验就绪，`query_count 21 → 2` 且延迟可区分 → `verified`。

**合同**：`BatchQuerySpec` 未知字段拒绝；`Recommendation` 机制枚举校验；`Finding(kind="n_plus_one")`
的 `verified` 结构证据校验；交接体 round-trip。

验证命令与慢查询一致：`uv run pytest`、`uv run ruff check`、`uv run mypy src`、重导出合同。

## 8. 开放决策

已确认：首版**一并打通 `verified`**（§4 的开关式批量干预纳入首版）；N+1 用**新增独立场景**
`n-plus-one-orders-search`。

仍待实现时锁定：

1. **`template_sql` 归一范围**：字面归一覆盖字符串/数值/`?`；布尔、日期、`IN` 列表等形状归一范围需
   在实现时锁定，避免归一过度把不同查询合并成同构。
2. **开关载体**：§4.1 的 `flag` 用环境变量 / 配置表 / 启动参数，由 A 侧实现时选择并记录。
