# Failure-Driven Hardening and Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Do not use subagents without the user's confirmation. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 消除全量真实评估暴露的失败，冻结版本并交付可复核的 `overall_passed=true` 证据。

**Architecture:** 以阶段 3 的失败矩阵为唯一修复队列。每个失败先回放完整原始包，再定产品、评分器、数据或环境归因；每个独立缺陷有 RED 测试、最小修复、新版本真实复跑。最后在同一冻结版本上运行 45 例和工程门槛。

**Tech Stack:** Python 3.13、pytest、AGH/MCP、Docker/MySQL、现有评测器。

**Spec:** `docs/superpowers/specs/2026-10-15-evaluation-closure-design.md`

## Global Constraints

- 不知道阶段 3 的具体失败前，不能预写“修复方法”或改评分权重；此计划给出缺陷处理与验收协议。
- 不下调金标准/阈值，不删困难用例，不以 `--only-bundled`、合成探针、静态测试替代真实运行。
- 评分器或数据集确有错误时，独立审查原始证据，保留旧报告、写迁移说明并更换哈希与评估 ID。
- 每次产品代码、模型配置、数据集或评分器变化后，旧运行不能混入最终 45 例；保持单一版本。
- 不使用子 Agent，除非用户明确同意。

## Review Focus

- 某用例通过但引入新的误验证：全局闸门仍失败；在 Task 2 测。
- 某次复跑只替换失败包导致混版：评测器拒绝；在 Task 2 测。
- 修复导致其他机制退化或不支持类别误报：受影响族和对照用例复跑；在 Task 1 测。
- 模型回答格式正确但原始事实缺失：不得补造 trajectory/retest/restore；在 Task 1 测。
- 评分器迁移仅提高某分而损伤其他用例：金标准和反例回归必须揭示；在 Task 1 测。

---

### Task 1: 按失败簇修复

**Files:**
- Input: `docs/development/acceptance/2026-10-15-full-evaluation-matrix.md`、对应原始运行包
- Modify: 由每个已归因失败决定；在矩阵中列出精确文件与测试后才能动代码
- Update: `docs/development/acceptance/2026-10-15-evaluation-closure.md`

**Interfaces:** 每个失败簇输出：原始证据引用、归因、最小 RED 测试、修复 commit、新运行包和对应 gate 变化。

- [ ] **Step 1: 对失败逐个审计全记录。** 同看 `business-tool-calls.jsonl`、`session.jsonl`、`bundle.json`、`summary.json`、SQL/计划/锁、报告、评分及恢复；区分“没跑到”“证据不足”“误验证”“修复错误”“评分误判”。
- [ ] **Step 2: 为每个同根因失败簇写一页小计划。** 写清文件/接口、RED 测试名和断言、修复边界、受影响用例、反例、预期 gate；多类故障不混成一大改动。
- [ ] **Step 3: 执行 RED→最小修复→GREEN。** 先跑定向测试，再跑 `./scripts/check.ps1`、数据集三守卫和评测器单测。评分器缺陷仅改评测侧，产品缺陷仅改 SUT/运行器，环境缺陷保留实际失败轨迹。
- [ ] **Step 4: 开新评估 ID 复跑受影响族和反例。** 检查 false_verified、漏判、修复正确性、恢复、成本；若失败仍在，继续同一证据循环。记录失败前后不同版本，禁止直接比作同口径分数。
- [ ] **Step 5: 每簇提交代码、测试与脱敏证据摘要。** 不提交原始敏感 session；摘要列出完整包位置和哈希。

### Task 2: 冻结版本后全量重跑

**Files:**
- Runtime output: `runtime-data/<final-evaluation-id>/`（45 个原始包、45 个导出包、评分报告）
- Update: `docs/development/acceptance/2026-10-15-evaluation-closure.md`
- Test: `datasets/evaluation/test_run_eval.py` 和全部工程守卫

**Interfaces:** 同阶段 3 的真实运行与导出命令；最终评分不带 `--only-bundled`。

- [ ] **Step 1: 冻结 Agent commit/源码哈希、模型配置、目标版本、数据集、评测器/评分器哈希。** 记录新评估 ID，确认无未提交产品修改；核验 45 个 case ID 清单。
- [ ] **Step 2: 从零执行 45 个独立 AGH 任务与必要的独立修复/复测。** 不复用旧会话或旧包；保存退出码与清理证据；检查没有跨例污染。
- [ ] **Step 3: 导出并全量评分。** 运行 `uv run --no-project --python 3.13 python datasets/evaluation/run_eval.py --runs <final-runs-dir> --out <final-score-dir> --cases-root datasets`；断言 `cases_evaluated=45`、`cases_missing_bundle=[]`、`false_verified_count=0`、`all_cases_passed=true`、`version_bound=true`、`overall_passed=true`。
- [ ] **Step 4: 工程复核。** 跑 `./scripts/check.ps1`、45 例 schema/隔离/SUT 分离守卫、评测器单测、14 例 fixture 回归；单列工程结果与真实 Agent 结果。
- [ ] **Step 5: 人可读验收报告。** 先写“什么能用、什么仍不可信、下一步”，再列 45/45、误验证、修复/克制/越界、模型与版本、评估 ID、原始包位置和复现命令；只在 Step 3 真通过时写“评估通过”。

**Stage exit:** `global.overall_passed=true` 且所有原始包可复核、资源恢复完整。若受外部环境阻断或任何 gate 失败，报告“未通过/未运行”及精确原因，不得换用较弱口径。
