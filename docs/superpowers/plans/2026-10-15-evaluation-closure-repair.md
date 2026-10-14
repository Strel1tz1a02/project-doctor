# Diagnosis-to-Repair Real Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Do not use subagents without the user's confirmation. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 用真实持久化诊断结果证明“该改、怎么改、改后有效”，并证明证据不足和越界时会停。

**Architecture:** 先把已有 `query_shape` 合同接入真实运行时，再沿用 `repair_handoff.py`、独立 AGH 修复会话、`RepairWorkflow`、`DiagnosisRetestService` 和登记/导出脚本。每个事实从同一 task 的持久化 bundle 与原始会话导出；合成探针只用于接口回归。

**Tech Stack:** Python 3.13、pytest、AGH/MCP、Docker/MySQL、现有数据集评测器。

**Spec:** `docs/superpowers/specs/2026-10-15-evaluation-closure-design.md`

## Global Constraints

- 修复 Agent 只接收实际 task/finding ID 与持久化证据；不能看到 `case.json`、gold Finding、期望补丁。
- 诊断和修复是独立会话；没有修复会话时，不得把无 `RepairRecord` 记为正确克制。
- `retested` 只由诊断侧依据独立复测写入；构建成功或单次变快不足以证明修复有效。
- 原始诊断报告不改写；补丁、业务结果、SQL/计划、锁、恢复证据互相校验任务、commit 与证据引用。
- 先完成第一阶段六例真实复跑；若执行环境缺失，工程改动可继续，但本阶段验收保持“未运行”。

## Review Focus

- Finding 不存在、过期或证据损坏：handoff 拒绝，修复会话不能凭猜测开始；在 Task 1 测。
- `lead`/`unclassified` 没有可归因修复：独立修复会话留下停手理由和无补丁事实；在 Task 2 测。
- 补丁打在诱饵文件、越过 Java/XML 允许范围或改了业务语义：拒绝成功；在 Task 2 测。
- 构建成功而复测业务不一致、收益不可区分或恢复失败：不得输出 `retested`；在 Task 3 测。
- 登记文件缺失、会话 ID 错配、最终 bundle 与诊断报告不一致：导出拒绝或明确缺失；在 Task 3 测。

---

### Task 1: 审计现有交接链并锁定真实样本

**Files:**
- Read: `src/project_doctor/workflows/repair_handoff.py`, `src/project_doctor/workflows/repair_facts.py`, `scripts/export_repair_handoff.py`, `scripts/register_repair_facts.py`, `scripts/export_evaluation_run.py`
- Create: `docs/development/acceptance/2026-10-15-repair-real-run.md`
- Test: `tests/repair/test_handoff_export.py`, `tests/repair/test_repair_facts.py`, `tests/runtime/test_repair_handoff_evaluation.py`

**Interfaces:** `export_repair_handoff(...)` → 独立会话 → `TaskBundle.repairs` → `register_repair_facts.py --home ...` → `export_evaluation_run.py --home ... --case-id ... --out ...`。

- [ ] **Step 1: 跑现有合同测试。** `uv run --locked pytest -q tests/repair/test_handoff_export.py tests/repair/test_repair_facts.py tests/runtime/test_repair_handoff_evaluation.py`；记录实际通过/失败项，不把合成探针当真实通过。
- [ ] **Step 2: 选真实样本并记录判定。** case-44、case-07 是应修候选；case-16、case-42 是证据不足/收益不可归因；case-46 是越界停。记录各自诊断状态、是否有 `expected.repair`/`expected.handoff`，评测字段仅评测器读取。
- [ ] **Step 3: 做一条手工可审计的真实交接 dry run。** 运行前检查 Docker Linux engine、MySQL DSN 是否存在、AGH/profile、目标启动、代码版本。若缺任一前提，记阻断并停止真实运行步骤；不要造持久化 Finding。
- [ ] **Step 4: 对真实失败写最小 RED 测试。** 明确失败发生于 handoff、Agent 决策、补丁、复测、登记或导出哪一层；没有失败就不改产品代码。测试必须覆盖 Review Focus 对应条件。

### Task 2: 接通 N+1 的真实 query-shape 实验

**Files:**
- Modify: `src/project_doctor/integrations/runtime_factory.py`, `agh/diagnosis-instructions.md`
- Reuse: `src/project_doctor/features/experiments/interventions.py` 的 `parse_query_shape_recipe`, `src/project_doctor/models/experiment.py` 的 `variable='query_shape'`/`candidate_batch`
- Test: `tests/runtime/test_experiment.py`, `tests/diagnosis/test_n_plus_one.py`

**Interfaces:** `ExperimentSpec(variable='query_shape', levels=('baseline','candidate_batch'), intervention_recipe_ref='recipe:<name>')` → 从受控 recipe 解析 flag 切换 → 原始 baseline/candidate SQL 调用、业务结果、统计、恢复证据 → 持久化 `ExperimentResult` → `check_n_plus_one`。

- [ ] **Step 1: 写 RED 测试。** 当前 `runtime_factory.py` 对所有变量调用 `parse_index_recipe`；证明 `query_shape` 被拒或误执行。增加有效受控 flag recipe、非法字段/任意路径拒绝、两级同快照同业务结果、候选批量 SQL 次数收敛、取消/失败恢复 baseline 的测试。不能靠合成 Finding 代替运行时观测。
- [ ] **Step 2: 运行 `uv run --locked pytest -q tests/runtime/test_experiment.py tests/diagnosis/test_n_plus_one.py` 确认 RED。**
- [ ] **Step 3: 在运行适配层按 `spec.variable` 分派 recipe 与干预。** 复用现有预算、独占、采样、锁/缓存、制品哈希、恢复与结算协议；只允许目标声明的受控 flag，不让模型提交任意 shell/SQL/路径。若目标没有可逆开关，产出 `lead` 和限制，不伪造 candidate_batch。
- [ ] **Step 4: 跑 GREEN、`./scripts/check.ps1` 和一例真实 case-44 诊断。** 先确认实际 SQL 数量/位置/请求一致性与恢复，再允许后续修复会话读取 Finding。更新 `agh/README.md` 的能力边界，仅写实测范围。
- [ ] **Step 5: 单独提交运行时接通与测试。**

### Task 3: 独立修复决策与补丁

**Files:**
- Modify only on evidenced failure: `agh/repair-instructions.md`, `src/project_doctor/workflows/repair.py`, `src/project_doctor/workflows/repair_handoff.py`
- Tests, as owned by changed module: `tests/repair/test_handoff_export.py`, `tests/repair/test_workflow.py`, `tests/integration/agent/test_mcp_protocol.py`

**Interfaces:** 消费持久化 handoff 的 task/finding/evidence/commit；产出真实修复会话、`RepairRecord` 或明确的停手决定。

- [ ] **Step 1: 用 case-44/07 和 case-16/42/46 各跑独立修复会话。** 保存诊断会话、修复会话、business tool calls、原始 bundle 与源代码快照；记下运行命令和版本。
- [ ] **Step 2: 逐条检查“是否该改、改哪里”。** 应修样本必须命中实际缺陷且补丁位于允许源文件；克制样本必须有会话和停手理由、无补丁。发现错误时先把具体轨迹变成 RED 测试。
- [ ] **Step 3: 对已复现错误做最小修复并跑 GREEN。** 使用 Step 2 对应测试文件及 `./scripts/check.ps1`；不得通过加入 case ID/答案、扩大允许补丁范围或放松证据阈值实现通过。
- [ ] **Step 4: 提交独立可审查改动。** 只提交产品代码、测试和脱敏运行摘要；原始 session 保留在忽略目录，并在摘要给相对路径及哈希。

### Task 4: 独立复测、登记和真实评分

**Files:**
- Modify only on evidenced failure: `src/project_doctor/workflows/diagnose_retest.py`, `src/project_doctor/workflows/repair_facts.py`, `scripts/register_repair_facts.py`, `scripts/export_evaluation_run.py`
- Test: `tests/runtime/test_repair_handoff_evaluation.py`, `tests/runtime/test_evaluation_export.py`, `tests/repair/test_repair_facts.py`
- Update: `docs/development/acceptance/2026-10-15-repair-real-run.md`

**Interfaces:** `run_independent_retest.py --source-home <run> --out-home <new> --service-image <image>`；最终 bundle + 修复会话 → `handoff.json`/`repair.json` → 运行包 → `run_eval.py` 子集评分。

- [ ] **Step 1: 给应修样本做独立复测。** 至少核对业务结果、基线与补丁后可比请求、收益、锁与恢复；`gain_attributable` 只可来自实际 `retested` 记录。
- [ ] **Step 2: 登记并导出。** 使用现有 CLI，检查会话/task/finding/commit/补丁行身份；缺事实时保留缺失，不手填“成功”布尔值。
- [ ] **Step 3: 以 `--only-bundled` 评分本阶段真实样本。** 此处只代表所选子集；逐项核对 handoff_valid、修复四项、诊断闸门及原始证据。对失败写 RED 测试、最小修复、再评分；旧报告不覆盖。
- [ ] **Step 4: 至少对一例应修、一例克制、一例越界各重复三次独立任务。** 统计正确决策、补丁位置、业务一致性、可归因收益、误验证与失败原因；同一版本和同一评分口径内比较。
- [ ] **Step 5: 跑 `./scripts/check.ps1` 与评测器单测，完成验收摘要。** 标出所有未运行项和原始包位置，不以合成 case-44 探针宣称整体通过。

**Stage exit:** 应修、克制、越界三条真实路径均有独立会话和完整运行包；应修路径完成独立复测且无误验证。未满足时列出失败闸门并继续针对性修复。
