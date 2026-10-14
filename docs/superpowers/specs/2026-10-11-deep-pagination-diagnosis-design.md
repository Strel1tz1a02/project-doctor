# 深分页（大 OFFSET）诊断设计（v0.1）

> 状态：设计稿，待复核。本文规定「深分页」（问题四）的诊断判据、数据合同，以及与问题修复层的
> 数据交接格式。沿用 [平台架构设计](2026-10-02-platform-architecture-design.md) 的五层职责，
> 复用慢查询（[slow_query.py](../../../src/project_doctor/features/diagnosis/slow_query.py)）与
> N+1（[n_plus_one.py](../../../src/project_doctor/features/diagnosis/n_plus_one.py)）已建立的
> 三路分级、锁排除、波动门槛与证据引用原则。检测原理与因果链见
> [performance-agent-deepdive-04-deep-pagination.md](../../diagnosis/performance-agent-deepdive-04-deep-pagination.md)。

## 1. 目标与交付边界

- **首版交付**：在同一有效请求内**检测深分页结构**，并通过 **keyset 干预实验**打通 `verified`——
  把 `LIMIT N OFFSET M` 换成 `WHERE 排序列 > 上次值 ORDER BY 排序列 LIMIT N`，证明扫描量由
  ≈M+N 降到 ≈N、延迟下降、业务结果一致。
- **干预与修复分离**：实验干预是**临时、可逆的运行时开关**（见 §4），用于证明机制；
  诊断产出的 `DeepPaginationSpec` 才是交给修复层做**永久代码改写**的结构化交接（见 §5）。
- **不宣称**：把「带 OFFSET 的 SQL」直接当深分页（浅页 OFFSET=0/小页也在用 OFFSET）；
  把「加索引」当深分页的修复（索引救不了 OFFSET）；把「扫描行数大」单指标当根因（须与全表扫描区分）。

## 2. 诊断判据（`check_deep_pagination`）

### 2.1 检测信号（提示性）

- 同一条 SQL 的 `normalized_sql` 文本含正 `OFFSET`（`LIMIT n OFFSET m` 或 `LIMIT m, n`）；
- `rows_examined` 大而 `rows_returned` 小，且 `rows_examined ≥ OFFSET`——跳过的 M 行确实被扫描计入；
- 请求耗时随 OFFSET（页码）增大而上升（对照组体现）。

### 2.2 结构证明（门槛）

同时满足以下才从「提示」升为「证明」：

1. **结构**：基线观测里存在含正 `OFFSET` 的 SQL 调用（`extract_limit_offset` 提取 `offset > 0`），
   共享同一参数化 `template_sql` 与 `code_location`。
2. **代价复现**：该调用 `rows_examined ≥ OFFSET`（跳过的 M 行确实被扫描），否则 OFFSET 代价未复现。
3. **共存判别**：若 `rows_examined` 远超 `OFFSET + 页大小`（≥1.5×），说明存在整表扫描等额外成本
   淹没 OFFSET（`type=ALL` 主导），记 `limitation`「整表扫描共存」，判 `lead` 并提示迭代先修全表扫描。
4. **排序列**：能从参数化模板提取 `ORDER BY` 的稳定排序列，作为 keyset 修复的结构化目标；
   无法提取则不构成结构化交接。
5. **排除干扰**：沿用慢查询的锁排除（LOCK_TIME 实测表/行锁 + MDL 残差）、波动门槛、
   业务结果一致与恢复校验。

### 2.3 三路分级

| 结论 | 条件 | 说明 |
|---|---|---|
| `verified` | keyset 干预使同排序列的扫描量由 ≈M+N 降到页大小量级，且延迟下降过波动门槛、业务结果一致 | 依赖 keyset 干预实验（§4） |
| `unclassified` | 基线无正 `OFFSET`（`offset=0` 或非分页查询） | 深分页在当前数据/代码下未复现 |
| `lead` | 检测到深分页结构但无 keyset 干预证实收益；或证据不足（缺排序列 / 缺代码位置 / 扫描未复现 / 锁或波动未排除 / 整表扫描共存） | 强证据 + 结构化交接，克制下结论 |

### 2.4 与慢查询的边界（共存判别）

深分页与全表扫描**正交、可叠加**（见 deepdive §4.3）：一条 SQL 可以只有深分页（`type=index` 但
`OFFSET` 大）、只有全表扫（`type=ALL` 但无 `OFFSET`），或两者都有。区分**不靠 `Rows_examined` 单指标，
也不靠 `type`**（深分页本身也可能 `type=ALL`）：

- 慢查询 → 索引干预降低扫描量；
- 深分页 → SQL 含正 `OFFSET` + keyset 干预降低扫描量。

修复顺序：先修全表扫描（消除 `type=ALL`），复测后再量化 OFFSET 的剩余成本、决定是否改 keyset。
首版以「整表扫描共存 → `lead` + 提示迭代」的形式落地该判别（§2.2(3)）。

## 3. 数据合同变更

### 3.1 `ProblemKind`（`models/common.py`）

```python
ProblemKind = Literal["slow_query", "n_plus_one", "deep_pagination", "unclassified"]
```

### 3.2 结构化修复交接 `DeepPaginationSpec`（新增 `models/deep_pagination.py`）

类比 N+1 的 `BatchQuerySpec`，深分页的修复交接使用结构化 `DeepPaginationSpec`，使修复层可确定性
消费，不靠自由文本推断。注意：它是**永久代码改写**的交接体，与 §4.1 的**临时干预配方**
`PaginationRecipe`（证明机制用）是两个概念——前者交给修复层，后者给实验运行时。

```python
PaginationStrategy = Literal["keyset", "max_page_limit"]


class DeepPaginationSpec(Contract):
    kind: Literal["deep_pagination"] = "deep_pagination"
    strategy: PaginationStrategy
    query_template: Identifier  # 参数化深分页 SQL 模板（含 LIMIT ? OFFSET ?）
    sort_column: Identifier  # keyset 稳定排序列，如 "id"
    code_location: CodeLocation  # OFFSET 查询定义位置（mapper 方法）
    observed_offset: NonNegativeInt  # 观测到的 OFFSET 值 M
```

### 3.3 `fix_spec` 判别联合（`models/finding.py`）

`Finding.fix_spec` 由 `BatchQuerySpec | None` 扩展为判别联合：

```python
fix_spec: Annotated[
    BatchQuerySpec | DeepPaginationSpec | None,
    Field(discriminator="kind"),
] = None
```

`kind` 字面量互斥（`n_plus_one` / `deep_pagination`），两个 `fix_spec` 都带 `kind` + `strategy`，
故 `fix_spec_matches_kind_and_mechanism` 校验器天然兼容两种；仅把校验器错误文案的「n_plus_one」
前缀去掉，改为通用表述。

### 3.4 校验器与路由去硬编码

- `models/finding.py` 的 `verified_requires_structural_evidence` 白名单加 `"deep_pagination"`。
- `workflows/tools.py` 的假设 `supported` 判定加 `deep_pagination + explanation == "deep_pagination_keyset"`。

## 4. keyset 干预实验与实验变量泛化（打通 `verified`）

`verified` 需要一个「keyset」候选组。沿用 N+1 的变量泛化：

- `ExperimentSpec.variable: Literal["index", "query_shape", "pagination"]`
- `ExperimentLevel: Literal["baseline", "candidate_index", "candidate_batch", "candidate_pagination"]`
  （慢查询用 `candidate_index`；N+1 用 `candidate_batch`；深分页用 `candidate_pagination`。）

`variable_matches_candidate_level` 校验器改为显式三路映射（原 `else → candidate_batch` 写法会把
`pagination` 错误落入 `candidate_batch`）。

### 4.1 干预配方 `PaginationRecipe`（临时、可逆）

与 `QueryShapeRecipe` 对称，深分页的干预配方也是可逆的受控变更——demo 的 `OrderService` 分页逻辑
内置两条实现分支（`offset` 深页 / `keyset` 游标），由配置开关切换。

```python
class PaginationRecipe:  # frozen dataclass, features/experiments/interventions.py
    strategy: Literal["keyset", "max_page_limit"]
    flag: Identifier  # 应用开关，如 "app.pagination.mode"
    baseline_value: Identifier  # 如 "offset"
    candidate_value: Identifier  # 如 "keyset"
    sort_column: Identifier  # keyset 稳定排序列，如 "id"
    query_template: Identifier  # 参数化深分页 SQL 模板
```

运行时语义：`baseline` 组 = 开关为 `baseline_value`；`candidate_pagination` 组 = 开关设为
`candidate_value` → 重跑 → 恢复开关为 `baseline_value`。对称可逆，与 `IndexRecipe` 的
`create_sql` / `drop_sql`、`QueryShapeRecipe` 的 flag 翻转对齐。

### 4.2 `verified` 门槛

`candidate_pagination` 组须同时满足，才 `verified`：

- 同排序列的扫描量中位数由 ≥ OFFSET 降到 ≤ 2×页大小（消除 M 行跳扫）；
- 请求延迟下降且过波动门槛（复用 `distinguishable`）；
- 业务结果一致（`result_digest` 两组相同）；
- 排序列不变（keyset 只换分页语义，不改访问列）。

### 4.3 对 A 侧的依赖

- demo：`OrderService`/`OrderMapper` 增加 `keyset` 分支与开关读取（`page`→`last_id` 转换），`DataInitRunner` 不变。
- 运行时：新增 `pagination` 配方解析 + 开关应用/恢复 + 恢复校验（开关值回读 = `baseline_value`）。
- `integrations/observation/sql_probe.py` 的字面量/OFFSET 提取（B 侧以纯函数 `extract_limit_offset` 兜底，不依赖 A）。

## 5. 与问题修复层的数据交接格式

交接方向两条：诊断层 → 修复层（给出可复现的结构化修复目标），修复层 → 诊断层（复测回填验证结果）。
完整字段契约见 [handoff-to-fix-layer.md](../../development/b/handoff-to-fix-layer.md)「深分页交接」节。

### 5.1 诊断 → 修复层

交接体 = `Finding(kind="deep_pagination")` + `Recommendation` + `fix_spec`（`DeepPaginationSpec`）：

```json
{
  "finding_id": "finding-<sha>",
  "kind": "deep_pagination",
  "status": "lead",
  "scenario_id": "deep-pagination-orders-search",
  "code_locations": [
    { "commit": "<commit>", "path": "src/main/java/com/example/slowquery/mapper/OrderMapper.java", "line": 14 }
  ],
  "sql_call_ids": ["sql-<req>-page"],
  "recommendation": {
    "action": "把 OFFSET 分页改为 keyset 分页（WHERE id > 上次值 ORDER BY id LIMIT ?）",
    "mechanism": "keyset",
    "conditions": ["排序列为 id", "须在 id 上有索引且值稳定单调", "服务端缓存游标并处理并列值"],
    "costs": ["游标状态需随请求传递", "随机跳页需限制最大页"],
    "validation_status": "expected_mechanism"
  },
  "fix_spec": {
    "kind": "deep_pagination",
    "strategy": "keyset",
    "query_template": "SELECT * FROM orders WHERE status = ? ORDER BY id LIMIT ? OFFSET ?",
    "sort_column": "id",
    "code_location": { "commit": "<commit>", "path": "src/main/java/com/example/slowquery/mapper/OrderMapper.java", "line": 14 },
    "observed_offset": 100000
  }
}
```

### 5.2 修复层 → 诊断层（复测回填）

修复层按 `fix_spec` 改写 → 重跑正确性 + 基准负载 → 只回填 `Recommendation` 的复测字段
（`validation_status` / `measured_gain_percent` / `retest_experiment_ids`），不回写诊断判据。

### 5.3 交接不变量

- 诊断层**只产出** `validation_status="expected_mechanism"` 且 `measured_gain_percent=null` 的交接体，不声称已测收益。
- 修复层**不能改写**诊断判据、测试数据或通过标准；复测结果只回填复测三字段。
- 交接体与 `Finding.evidence_refs` / `sql_call_ids` 可追溯：修复层复测对照必须引用同一场景、数据快照与提交。
- `fix_spec` 为 `None` 时（排序列无法提取或结论为 `unclassified`）不构成结构化交接，修复层不得凭自由文本改写。

## 6. 落点文件与职责

| 文件 | 改动 | 责任 |
|---|---|---|
| `models/common.py` | `ProblemKind` 加 `deep_pagination` | B |
| `models/deep_pagination.py`（新增） | `DeepPaginationSpec` + `PaginationStrategy`（修复交接） | B |
| `models/observation.py` | `ExperimentLevel`/`CandidateLevel` 加 `candidate_pagination` | B |
| `models/experiment.py` | `ExperimentSpec.variable` 加 `pagination`；`variable_matches_candidate_level` 三路映射 | B |
| `models/finding.py` | `fix_spec` 判别联合；`verified` 白名单加 `deep_pagination` | B |
| `features/diagnosis/deep_pagination.py`（新增） | `check_deep_pagination` + `extract_limit_offset`（§2 判据 + 三路分级） | B |
| `features/experiments/interventions.py` | `PaginationRecipe` + `parse_pagination_recipe`（与 `QueryShapeRecipe` 对称） | B 契约 |
| `workflows/diagnose.py` | 按 `variable` 分派 `check_slow_query` / `check_n_plus_one` / `check_deep_pagination` | B |
| `workflows/tools.py` | 假设 `supported` 判定扩展 `deep_pagination` | B |
| `demo/reference/manifest.json` | 新增独立场景 `deep-pagination-orders-search`；移除既有场景 `uncovered_paths` 中的 deep-pagination | B |
| `scripts/export_contracts.py` | `MODULES` 加 `deep_pagination` | B |
| demo（Spring） | `OrderService`/`OrderMapper` 加 `keyset` 分支 + 开关读取 | A |
| A 运行时 | `pagination` 配方应用/恢复 + 开关回读校验 | A |

## 7. 测试与验证

**反例（不能升 `lead`/`verified`）**：

- 无正 `OFFSET`（`offset=0` / 非分页查询）→ `unclassified`；
- 有 `OFFSET` 但 `rows_examined < OFFSET`（跳扫代价未复现）→ `lead`；
- 整表扫描淹没（`rows_examined` 远超 `OFFSET + 页大小`）→ `lead` + 共存提示；
- keyset 干预未降扫描量 / 耗时不可区分 → `lead`；
- 缺代码位置 / 缺排序列 / 锁或波动未排除 / 恢复未验证 → `lead`。

**正例**：demo 的 `/api/orders/search` 深页（`page=5001`，`OFFSET≈100000`）→ 结构证明完整，产出
`lead` + `DeepPaginationSpec`；keyset 干预实验就绪后，扫描量 100020 → 20 且延迟可区分 → `verified`。

**合同**：`DeepPaginationSpec` 未知字段拒绝；`PaginationStrategy` 枚举校验；`extract_limit_offset`
两种 LIMIT 写法；`Finding(kind="deep_pagination")` 的 `verified` 结构证据校验；交接体 round-trip。

验证命令与慢查询/N+1 一致：`uv run pytest`、`uv run ruff check`、`uv run mypy src`、重导出合同。

## 8. 开放决策

已确认：首版**一并打通 `verified`**（§4 的 keyset 开关式干预纳入首版）；深分页用**新增独立场景**
`deep-pagination-orders-search`。

仍待实现时锁定：

1. **「深」的判定阈值**：首版以 `offset > 0` + `rows_examined ≥ OFFSET` 作为「代价复现」的判据，
   未引入「多少页才算深」的绝对阈值——浅页虽会被检出为 `lead`，但这是诚实的（它确实是 OFFSET 分页，
   只是尚未疼痛）。如需把「浅页」归为 `unclassified`，实现时再定阈值并记录。
2. **整表扫描共存的量化界**：首版以 `rows_examined ≥ 1.5×(OFFSET+页大小)` 作为「被淹没」的经验界，
   实现时可替换为 EXPLAIN `type=ALL` 的显式判别。
3. **开关载体**：§4.1 的 `flag` 用环境变量 / 配置表 / 启动参数，由 A 侧实现时选择并记录。
