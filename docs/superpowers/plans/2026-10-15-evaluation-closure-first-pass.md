# Evaluation Closure First Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user requires separate confirmation before subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复六例慢查询中已证实的 case-05 误验证与 case-02 评分误判，形成可追溯的六例真实复跑基线。

**Architecture:** Keep diagnosis decisions in `features/diagnosis` and scoring in `datasets/evaluation`. Read only hash-verified plans for selectivity screening. Fix evaluator handling of multiple limitation statements and source spans on the evaluator side. Preserve old score reports, then run fresh AGH tasks and score their exported bundles.

**Tech Stack:** Python 3.13, Pydantic, pytest, AGH/MCP, Docker/MySQL, existing standard-library evaluator.

**Spec:** `docs/superpowers/specs/2026-10-15-evaluation-closure-design.md`

## Global Constraints

- SUT and Agent may see only a case's `project/`, never `case.json` or evaluator assets.
- Do not merge `origin/fix/diagnosis-quality-selectivity-limitations`: it predates current main and would remove newer repair, provenance and evaluation work. Its focused tests may be consulted, not copied blindly.
- Existing `MeasurementPolicy` thresholds stay unchanged. A plan estimate never substitutes for measured scan rows or duration.
- Every new score records Agent/source, model, evaluator, dataset and scorer hashes plus the run-package path. Old reports remain unchanged.
- `--only-bundled` is for scorer fixture regression only; live acceptance needs every case bundle and `global.overall_passed`.
- No model tool may receive an expected decision, gold Finding or prewritten repair.
- 单人顺序执行；用户要求使用子 Agent 前先征得确认。

## Review Focus

- MySQL JSON v1 and v2 plans can nest multiple table nodes; a joined table's poor selectivity must be seen, and malformed plans must not crash diagnosis.
- `filtered` is an estimate; a high value can only withhold a broad `verified`, never prove a root cause or a measured gain.
- Limitation coverage assembled from several true statements must pass, while unrelated keyword stuffing or an omitted mechanism must fail.
- Code location for a multiline SQL annotation may point at its first line or a relevant inner line; a different method or file must still fail.
- A completed task, intact artifacts or a 14-case fixture score must never be labeled a passed live evaluation.

---

### Task 1: Guard low-selectivity conclusions

**Files:**
- Create: `src/project_doctor/features/diagnosis/plan_scope.py`
- Modify: `src/project_doctor/features/diagnosis/slow_query.py`
- Test: `tests/diagnosis/test_plan_scope.py`
- Test: `tests/diagnosis/test_slow_query.py`

**Interfaces:**
- Produce `all_filtered(plan: dict[str, Any]) -> list[float]` in the diagnosis feature: finite `[0, 100]` table `filtered` estimates from all v1/v2 table nodes; ignore missing/invalid numbers. Do not import an integration from a feature. This is supporting evidence, not the sole decision rule.
- Consume existing `verified_plans` and `SqlCall.plan_evidence_ids` in `check_slow_query`.

- [ ] **Step 1: Write RED tests.** Cover v1/v2 nested plans, joins, malformed values and missing evidence. A single observed filter value with no distribution proof cannot support a broad `verified` conclusion; multiple representative values with comparable measured benefit can. A high or low `filtered` estimate alone never proves either result. Preserve measured-row and duration gates.
- [ ] **Step 2: Run focused tests and confirm RED.** `uv run --locked pytest -q tests/diagnosis/test_plan_scope.py tests/diagnosis/test_slow_query.py`.
- [ ] **Step 3: Implement the smallest evidence-scope rule in `check_slow_query`.** Decide from the recorded parameter coverage, actual scan/duration samples and verified plan; treat `filtered` only as an estimate that can trigger uncertainty review. If existing `Scenario`/`ExperimentResult` cannot represent the parameter coverage, add the smallest typed field and persistence test before using it. Record the proven parameter/snapshot and untested range in `Finding.limitations`. Do not change `Impact` or `MeasurementPolicy`. Do not hardcode case IDs or a `filtered` cutoff.
- [ ] **Step 4: Run focused tests and `./scripts/check.ps1`; confirm GREEN.**
- [ ] **Step 5: Commit the four files.** `git commit -m "fix(diagnosis): constrain single-value index conclusions"`.

### Task 2: Correct evaluator false negatives without using gold in SUT

**Files:**
- Modify: `datasets/evaluation/metrics.py`
- Modify: `datasets/evaluation/contract.py`
- Modify: `datasets/case-02-slow-query-composite/case.json` (the SQL annotation spans source lines 14–23, while expected currently names only line 21).
- Test: `datasets/evaluation/test_metrics.py`
- Test: `datasets/evaluation/test_golden_bundle.py`
- Create: `datasets/docs/2026-10-15-evaluator-migration.md`

**Interfaces:**
- Keep the public `text_covers(declared: str, required: str) -> bool`; evaluate the combined declared limitations for one requirement, with explicit mechanism checks instead of case identifiers.
- Keep the existing `location_matches` default; add line 15 as a second evaluator-owned accepted `expected.code_locations` location for the same `findSlowOrders` SQL.

- [ ] **Step 1: Write RED tests.** Use the original case-02 report: separate truthful limitations together cover LIKE, N+1, COUNT and deep pagination; removing any one fails. A same-method position on the multiline SQL passes; another method/file fails. Also reject unrelated keyword stuffing. The SUT is never imported by these tests.
- [ ] **Step 2: Run evaluator tests and confirm RED.** `uv run --no-project --python 3.13 python -m unittest evaluation.test_metrics evaluation.test_golden_bundle` from `datasets/`.
- [ ] **Step 3: Implement evaluator-only correction.** Match each required mechanism across the full set of declared limitations while rejecting bare keyword lists; ignore defect catalog IDs as prose. Add the verified SQL start line as an accepted case-02 expected location; do not raise the global line tolerance. Record the case/score migration and regenerate hashes/ID for the new scoring version.
- [ ] **Step 4: Run all dataset evaluator tests, 45-case schema and two isolation guards.** Inspect all changed golden results; preserve the prior 4/6 report rather than overwriting it.
- [ ] **Step 5: Commit evaluator files and the version note.** `git commit -m "fix(eval): score composite limitations and SQL source spans"`.

### Task 3: Re-score history and attempt a fresh six-case diagnosis run

**Files:**
- Create: `docs/development/acceptance/2026-10-15-diagnosis-quality-first-pass.md`
- Runtime outputs: `runtime-data/<new-evaluation-id>/` (ignored, never commit raw sessions).

**Interfaces:**
- Consume the six original run packages under `runtime-data/serial-evaluation-20261013-retry3/` for scorer comparison; use fresh tasks for product acceptance.
- Produce original-versus-new scorer table and, when available, six fresh AGH run packages plus `report.json`/`report.md`.

- [ ] **Step 1: Freeze identity.** Record HEAD/source hash, model config reference, dataset/evaluator/scorer hashes, new evaluation ID, and source run-package paths. Check `docker info` for Linux, platform DSN presence without printing its value, AGH executable/profile and target image prerequisites.
- [ ] **Step 2: Re-score the historical six packages with the new evaluator.** Keep the old score unchanged and state which delta came from scorer changes; re-scoring is not a new Agent result.
- [ ] **Step 3: If prerequisites exist, run six new isolated AGH diagnosis sessions.** Use the repository's current AGH integration entry; first document the exact executable command and config in the acceptance note. Each case gets a new task/session; export the full task, tool, SQL/plan/lock, report and restoration evidence. Do not feed `case.json` to the Agent.
- [ ] **Step 4: Score with `datasets/evaluation/run_eval.py --runs <six-run-dir> --out <new-score-dir> --cases-root datasets --only-bundled` only for this selected-subset diagnosis review. Assert the report contains exactly case-01 through case-06; label it explicitly as six-case subset. Inspect each failed gate and the complete original bundle before attributing failures.
- [ ] **Step 5: Save the acceptance note.** If Docker/DSN/AGH is unavailable, record the exact missing prerequisite and mark real acceptance unrun. Commit the note without raw dumps or secrets.

**Stage exit:** 六例新运行包完整、同一版本、无误验证；case-02/05 的每个评分差异均能追到原始包。环境缺失时交付代码与阻断记录，标注“真实复跑未完成”，进入下一阶段前补跑。
