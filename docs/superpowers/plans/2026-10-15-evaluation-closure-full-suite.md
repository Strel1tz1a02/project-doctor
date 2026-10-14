# 45-Case Live Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Do not use subagents without the user's confirmation. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 对现有 45 例逐例完成真实 Agent 运行、导出和全量评分，准确暴露尚未通过的闸门。

**Architecture:** 先接通已有深分页合同的运行时干预，再核验执行环境与运行器，冻结单一 Agent/模型/数据集/评测器版本；每例独立任务、独立 AGH 会话和隔离目标；运行包由持久化事实导出。支持的三类尝试证据闭环，其余六类可给诚实 `lead`/`unclassified`，但必须实际运行，不能跳过。

**Tech Stack:** Python 3.13、AGH/MCP、Docker/MySQL、`datasets/evaluation/run_eval.py`。

**Spec:** `docs/superpowers/specs/2026-10-15-evaluation-closure-design.md`

## Global Constraints

- 先完成阶段 1 和 2 的真实验收；若其中有阻断，明确记录，本阶段不得宣称全量评估通过。
- Agent 只读取 `datasets/<case>/project/` 及公开症状；`case.json`、评测文档、评分器和答案只在模型结束后由评测侧读取。
- 本阶段不扩展第四类诊断。未知机制只给可核对线索或未定论，不能为了评分输出 `verified`。
- 不用 `--only-bundled` 做最终评分；不补写缺失运行包、不混用 Agent 版本、不改金标准阈值。
- 每次启动检查 Docker Linux、平台 DSN 是否存在、AGH daemon/profile/MCP selector 和目标镜像；DSN 值、密钥不写入报告。

## Review Focus

- AGH 旧 daemon/旧 cwd 造成串案：每例检查独立会话、目标路径与源码哈希；在 Task 1 测。
- 目标 prepare/finish 失败或任务 blocked：保留失败轨迹，不伪装 completed；在 Task 2 测。
- unsupported kind 被静态命中误升 `verified`：在 Task 2 与评分表复核。
- 恢复失败或容器残留：运行包标失败，清理只作用于本次创建资源；在 Task 2 测。
- 版本字段缺失或混版：全量评分必须失败；在 Task 3 测。

---

### Task 1: 接通深分页的真实 pagination 实验

**Files:**
- Modify: `src/project_doctor/integrations/runtime_factory.py`, `agh/diagnosis-instructions.md`
- Reuse: `src/project_doctor/features/experiments/interventions.py` 的 `parse_pagination_recipe`, `src/project_doctor/models/experiment.py` 的 `variable='pagination'`/`candidate_pagination`
- Test: `tests/runtime/test_experiment.py`, `tests/diagnosis/test_deep_pagination.py`

**Interfaces:** `ExperimentSpec(variable='pagination', levels=('baseline','candidate_pagination'), intervention_recipe_ref='recipe:<name>')` → 受控 offset/keyset 切换 → 同请求页数据、实际扫描量/耗时、SQL/计划/锁及恢复证据 → `check_deep_pagination`。

- [ ] **Step 1: 写 RED 测试。** 现有 runtime 把所有 recipe 当 index；测试有效受控 pagination flag、非法 recipe 拒绝、两级相同页结果、扫描/耗时证据和异常恢复。不存在稳定排序键或等价页结果时不得给 `verified`。
- [ ] **Step 2: 运行 `uv run --locked pytest -q tests/runtime/test_experiment.py tests/diagnosis/test_deep_pagination.py` 确认 RED。**
- [ ] **Step 3: 在运行适配层接上 pagination 分派。** 复用阶段 2 建立的受控 flag/预算/采样/恢复协议；不接受模型任意 SQL 或文件路径。目标不支持可逆切换时保持 `lead`/`unclassified` 并声明限制。
- [ ] **Step 4: 跑 GREEN、`./scripts/check.ps1`，再对 case-08/18 至少一例做真实诊断。** 核对实际 SQL、排序/页结果与恢复，更新 `agh/README.md` 的实测能力说明。单独提交代码和测试。

### Task 2: 运行器与版本预检

**Files:**
- Read: `agh/README.md`, `scripts/export_evaluation_run.py`, `datasets/evaluation/run_eval.py`, `datasets/README.md`
- Modify only if a verified gap exists: current AGH case runner under `agh/` or `scripts/`; do not treat an ignored `runtime-data/` helper as a product entry.
- Test: corresponding AGH runner tests under `tests/` (locate by `rg --files tests | rg 'agh|runner|agent'`)
- Create: `docs/development/acceptance/2026-10-15-full-evaluation-matrix.md`

**Interfaces:** 输入 case ID、公开 project 路径、冻结运行版本；输出独立 task/session home、资源清单与可导出的原始事实。

- [ ] **Step 1: 清点 45 个 case ID、problem_kind、期望诊断级别和 `expected.repair`/`expected.handoff`。** 把矩阵放评测侧摘要，禁止送给 Agent。
- [ ] **Step 2: 记录预检结果。** `docker info`、`$env:PROJECT_DOCTOR_PLATFORM_DSN` 是否存在、AGH 可执行文件/profile、MCP selector、目标镜像；冻结 HEAD、源码哈希、模型配置引用、数据集/评测器/评分器哈希和新的评估 ID。
- [ ] **Step 3: 核对当前运行入口。** 若 `agh/README.md` 的单例入口无法为每例生成全新 cwd/session/task，先写 RED 测试，做最小运行器修复，再跑对应测试。记录实际 CLI 命令；不得仅凭历史一次性 `runtime-data/` 脚本跑全套。
- [ ] **Step 4: 先跑三个小批次。** 至少覆盖正常、边界、失败各一例，并含受支持/不受支持类型；检查隔离、版本、证据、清理后再扩至 45 例。

### Task 3: 逐例真实执行与导出

**Files:**
- Runtime output: `runtime-data/<new-evaluation-id>/<case-id>/` 和 `<case-id>.json`（忽略目录，保留原始包）
- Modify only on reproduced failure: `scripts/export_evaluation_run.py`, 运行器或其直接依赖
- Test: `tests/runtime/test_evaluation_export.py`, 对应运行器测试
- Update: `docs/development/acceptance/2026-10-15-full-evaluation-matrix.md`

**Interfaces:** `scripts/export_evaluation_run.py --home <case-home> --case-id <case-id> --out <runs-dir>/<case-id>.json [--retest-home <retest-home>]`；需要修复的用例先按阶段 2 完成独立修复登记。

- [ ] **Step 1: 冻结代码后顺序运行全部 45 例。** 每例新 task、新 cwd、新 AGH 会话、新隔离资源；记录退出码、目标 commit、会话 ID 和清理结果。重试用新会话，不覆盖原失败包。
- [ ] **Step 2: 完整保存每例 `business-tool-calls.jsonl`、`session.jsonl`、`bundle.json`、`summary.json`、SQL/计划/锁证据、报告与恢复证据。** 有修复期望的用例走独立修复链；无可归因证据者如实停手。
- [ ] **Step 3: 用既有导出器逐例生成 45 个运行包。** 每包检查任务/会话/源码/版本/模型身份、证据引用和原始目录；缺字段写缺失，不推断成功。
- [ ] **Step 4: 查找共性失败。** 仅对同一层的可复现缺陷写 RED 测试并修复，运行对应单测与 `./scripts/check.ps1`；代码或评测器变化后开启新评估 ID、重跑受影响用例，并确保最终 45 包来自同一冻结版本。

### Task 4: 全量评分和失败矩阵

**Files:**
- Runtime output: `runtime-data/<new-evaluation-id>/score/report.json`, `report.md`
- Test: `datasets/evaluation/test_run_eval.py`, `datasets/evaluation/test_golden_bundle.py`
- Update: `docs/development/acceptance/2026-10-15-full-evaluation-matrix.md`

**Interfaces:** `uv run --no-project --python 3.13 python datasets/evaluation/run_eval.py --runs <45-runs-dir> --out <score-dir> --cases-root datasets`。

- [ ] **Step 1: 跑数据集守卫。** 从 `datasets/` 执行 `tools/validate_cases.py`、`tools/isolation_guard.py`、`tools/guard_sut_separation.py` 和 `python -m unittest discover -s evaluation -p 'test_*.py'`；保存实际输出。
- [ ] **Step 2: 不带 `--only-bundled` 运行上面的全量评分。** 退出码失败也保存报告；逐项检查 `cases_evaluated=45`、`cases_missing_bundle=[]`、`false_verified_count=0`、`all_cases_passed`、`version_bound`、`overall_passed`。
- [ ] **Step 3: 对每个失败用例建立表格。** 字段为 case ID、失败 gate、原始 task/session/包路径、产品/评分器/数据/环境归因、责任文件、下一步；必须先看完整运行记录再归因。
- [ ] **Step 4: 提交脱敏矩阵及版本指纹。** 原始运行包留本地可复核目录，不提交密钥或源码副本。若未通过，进入阶段 4；若通过，仍做阶段 4 的最终审计。

**Stage exit:** 45 个真实包和全量报告齐全、单一版本可追溯。此阶段的目的包含暴露失败；只在 `global.overall_passed=true` 时记为已通过。
