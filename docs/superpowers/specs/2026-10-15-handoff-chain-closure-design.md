# 交接链工程闭环设计（诊断 → 修正一体化评估打通）

日期：2026-10-15。状态：用户已确认方案与两处口径拍板。

## 背景与问题

诊断 → 修正一体化评估的两侧工作在不同分支上独立完成，尚未合并：

- **数据集侧**（main，`d744e8a`）：评估契约已就位——运行包顶层 `handoff` 块、`retest.repair` 四字段、指标 `handoff_valid` 与 4 项修复能力指标、首批一体化用例 `case-44`（应修）/ `case-46`（越界停）。
- **执行测侧**（本地 `codex/diagnosis-repair-handoff`，5 提交，基于 `a7b7a9b`）：只读交接导出（`workflows/repair_handoff.py` + `scripts/export_repair_handoff.py`）、修复 Agent 指令（`agh/repair-instructions.md`）、通用化修复与诊断所有权复测（`1183a89`）。其计划的 Task 3-4（评估导出接线）被显式推迟。

后果：评估器有契约但无真实数据来源，协作简报 `O-1` / `O-2` / `O-4` 持续挂起，`case-44/46` 的一体化评估无法真实运行。

已探明：两侧改动文件**零重叠**，`git merge-tree --write-tree` 试合并**完全干净**。

## 用户已确认的决策

1. **采用方案 1**：合并 `codex/diagnosis-repair-handoff` → `main`，然后补齐评估导出接线。不丢弃、不重写。
2. **`O-4` 口径收紧**：凡修复 Agent 尝试改动（提交补丁）即记 `attempted=true`；克制用例（`expected_to_change=false`）只在「修复会话真实存在且全程未产生 `RepairRecord`」时判 `repair_warranted=true`。修复会话缺失不得按克制计分（与 codex 计划 Review Focus「缺席会话不得记为克制」一致）。
3. **`gain_attributable` 由执行侧显式标注**：导出器依据持久化复测事实标注——`Recommendation.validation_status == "retested"` 且 `measured_gain_percent` 非空且业务断言通过时为 `true`。是否达到 `expected.improvement.min_improvement_percent` 的阈值判定仍归评测器（导出器不读 `case.json`，隔离红线不破）。

## 范围

**内**：合并分支；全量回归；`scripts/export_evaluation_run.py` 补齐 `handoff` 块与 `retest.repair` 四字段；协作简报追加闭环条目。

**外**（后续工作流，不在本设计）：B 诊断质量攻关（`fix/diagnosis-quality-selectivity-limitations` 的 rebase 与六例复跑）；A 比赛提交材料。

## 工作分解

### 第 1 步：合并与回归基线

- 在 `main` 上 `git merge codex/diagnosis-repair-handoff`（预期无冲突；出现冲突即停止并报告，不强行解）。
- 全量回归，全部通过才进入第 2 步：
  - `scripts/check.ps1`（pytest + Ruff + mypy strict）；
  - `datasets/` 三守卫：`validate_cases.py`（45/45）、`isolation_guard.py`（45/45）、`guard_sut_separation.py`；
  - `python -m unittest discover -s evaluation` 与 `-s tools`；
  - 金标准回归：`test_golden_bundle.py`（14 例、误验证 0、`mean_total = 0.8762` 不变——合并不得污染存量分数）。

### 第 2 步：`handoff` 块导出

在 `export_evaluation_run.py` 新增可选 `handoff` 顶层块，仅当被导出的任务存在修复交接时产出。字段来源：

| 字段 | 来源 |
| --- | --- |
| `task_id` | 被导出任务 ID |
| `finding_id` | `TaskBundle.repairs[].finding_id` 指向的持久化 Finding |
| `repair_id` | `TaskBundle.repairs[].id` |
| `source_commit` | `RepairRecord.source_commit`（须与任务 `ProjectInput.commit` 一致，不一致拒绝导出） |
| `diagnosis_session_id` / `repair_session_id` | 运行编排侧提供的会话标识（导出参数显式传入，导出器不猜测）；二者相同或缺失时不产出 `handoff` 块并记录原因 |
| `finding_from_this_run` | Finding 为该任务持久化产物（自 `TaskStore` 装载且非外部注入）即 `true`；导出器无法确认时拒绝产出 `handoff` 块（红线不降级） |
| `build_result` | 自 `RepairRecord` 构建事实派生：`build_ref` 缺失或构建失败状态 → `"failed"`，否则 `"ok"` |

### 第 3 步：`retest.repair` 四字段导出

仅当任务存在修复活动时产出（缺省为 `None`，与「尝试但失败」严格区分）：

| 字段 | 来源 |
| --- | --- |
| `attempted` | 存在 `RepairRecord` → `true`；修复会话存在但无 `RepairRecord` → `false`（克制路径） |
| `patch_present` | `patch_sha256` 非空 ∧ `patch_ref` 非空 ∧ `status ∈ {built, retesting, retested}` |
| `patch_files` | 从持久化的补丁 diff 解析**实际改动行**，平铺为 `[{"path", "line"}]`；绝不使用期望缺陷位置冒充 |
| `gain_attributable` | 按用户拍板：复测事实齐备（`validation_status=="retested"` ∧ `measured_gain_percent` 非空 ∧ 业务断言通过）时 `true` |

### 第 4 步：协作简报闭环

在 `datasets/docs/对接执行测-协作简报.md` 追加条目：

- `O-1` → 已闭环（四字段已产出，附导出样例路径与回归证据）；
- `O-2` → 已闭环（`patch_files` 采用平铺 `[{path,line}]`，自补丁 diff 解析实际改动行）；
- `O-4` → 已闭环（收紧口径，附 `case-42/43` 克制探针结果）。

### 第 5 步：端到端验证

- `case-44`（应修）：模拟/真实修复运行包 → `handoff_valid=true`、4 项修复指标可判定且语义正确；
- `case-46`（越界停）与 `case-42/43`（克制）：无补丁路径 → 克制指标正确、`attempted=false` 成立；
- 反例：篡改 `finding_from_this_run` / 会话相同 / 构建失败 → 对应闸门必须判负；
- 全量回归复跑（同第 1 步清单）。

## 错误处理

- 合并出现非预期冲突：停止、报告冲突清单，不自动取舍。
- 导出器遇缺证据（会话标识缺失、Finding 来源不可确认、提交不一致）：**拒绝产出对应块并记录原因**，不产出半成品字段；评测器对声明了 `expected.handoff` / `expected.repair` 的用例缺块时按既有规则判不达标。
- 任何回归失败：先修复再推进，不降低门槛、不跳过测试。

## 测试

- `tests/runtime/test_evaluation_export.py`：`handoff` 块字段齐备性、会话相同/缺失时拒绝导出、提交不一致拒绝、构建失败映射。
- `tests/repair/`：四字段派生（含 `patch_files` 实际行提取、克制路径 `attempted=false`、缺失 `RepairRecord` 与缺席会话的区分）。
- 金标准回归不变式：`GOLDEN_MEAN_TOTAL = 0.8762`、误验证 0。
- 端到端探针沿用 `evaluation.test_metrics` 的真实用例探针模式。

## 验收标准

1. 合并后全部回归绿（第 1 步清单）；
2. 导出器能产出含 `handoff` 与 `retest.repair` 的运行包，`case-44` 探针 `handoff_valid=true`、修复四项可判定；
3. 克制/越界路径语义正确（`case-42/43/46`）；
4. 协作简报 `O-1` / `O-2` / `O-4` 标记「已闭环」并附证据；
5. 存量金标准分数零漂移。
