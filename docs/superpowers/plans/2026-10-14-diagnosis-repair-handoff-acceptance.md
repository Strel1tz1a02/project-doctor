# Diagnosis-to-Repair Handoff and Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user requires confirmation before using subagents; execute natively unless they explicitly choose otherwise. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that an independent repair Agent consumes a real persisted diagnosis, makes the right change or declines it, and receives a diagnosis-owned effect verdict across repeated runs.

**Architecture:** Keep the existing AGH and Project Doctor MCP loops. Add a read-only handoff export from `TaskStore.load_bundle`; launch a separate repair AGH session with only the persisted task/finding identifiers and source tools. Export repair facts from the final `TaskBundle.repairs` and verified artifacts into the existing dataset evaluator. No gold Finding or expected answer enters either Agent session.

**Tech Stack:** Python 3.13, Pydantic, existing MySQL `TaskStore`, AGH CLI/MCP, Docker/MySQL, pytest, dataset evaluator.

**Spec:** `docs/superpowers/specs/2026-10-14-generic-source-repair-design.md`; evaluation contract: `datasets/docs/运行包采集模块交接说明.md` §5.4 and `datasets/docs/Agent评估方法.md` repair metrics.

**Scope update (2026-10-14):** The user requested functionality only and deferred evaluation. Tasks 1-2 are the active delivery. Tasks 3-4 remain a future evaluation plan; their checkboxes are not acceptance requirements for this delivery. The diagnosis runtime currently executes index experiments only, so this change does not claim live N+1 or pagination diagnosis experiments.

## Global Constraints

- Diagnosis and repair may be separate AGH sessions; both use the same persisted task identity.
- Repair consumes actual `Finding` and evidence; no dataset `case.json`, gold Finding, expected fix, or prewritten patch enters the prompt.
- Repair may choose no change. Absence of a `RepairRecord` alone is insufficient proof that the repair Agent ran.
- Only diagnosis may mark `Recommendation.validation_status=retested` and report measured gain.
- Keep the current Java/MyBatis source scope: committed `src/main` Java/XML. An index-only case requiring schema DDL is not a positive source-repair acceptance case.
- Do not alter source, evaluator, tests, schema, data, or build configuration through the model patch.
- Do not put credentials or model responses containing secrets into tracked artifacts.

## File Structure

- `src/project_doctor/workflows/repair_handoff.py`: read-only, evidence-checked candidate export from one persisted task.
- `scripts/export_repair_handoff.py`: CLI composition with settings, MySQL store and file evidence reader.
- `agh/repair-instructions.md`: separate repair Agent prompt, decision and tool sequence.
- `scripts/export_evaluation_run.py`: attach final durable repair state and actual patch locations to the existing evaluation payload.
- `tests/repair/test_handoff_export.py`, `tests/runtime/test_evaluation_export.py`: contract and refusal tests.
- `docs/development/acceptance/`: exact commands, run identities and observed results.

## Review Focus

- A diagnosis `lead` with corrupt evidence or stale commit must not become a repair target; test rejection before AGH sees source.
- No persisted Finding or an `unclassified` result must still produce an auditable no-change repair session; test that an absent session is not scored as restraint.
- A failed or unknown repair must not appear as an attributable gain; test all `RepairRecord.status` values.
- A patch targeting a decoy must export its actual changed lines, never the expected defect location; test line extraction from the stored diff.
- Diagnosis report and final bundle can differ only in the three authorized retest fields; test rejection of all other Finding changes.

---

### Task 1: Read-only persisted handoff

**Files:**
- Create: `src/project_doctor/workflows/repair_handoff.py`
- Create: `scripts/export_repair_handoff.py`
- Test: `tests/repair/test_handoff_export.py`

**Interfaces:**
- Consumes: `TaskStore.load_bundle(task_id) -> TaskBundle`, `EvidenceReader.verify(refs) -> EvidenceCheck`.
- Produces: `async export_repair_handoff(store: TaskStore, reader: EvidenceReader, task_id: str) -> dict[str, object]` with task/correlation/commit, each persisted candidate's id/kind/status/evidence/locations/recommendation, and explicit empty-candidate state.

- [x] **Step 1: Write failing tests.** Assert a real persisted candidate is exported without dataset fields; corrupt evidence and wrong commit fail; no eligible Finding returns an explicit empty list.
- [x] **Step 2: Run `uv run --locked pytest -q tests/repair/test_handoff_export.py`.** Failed with missing module.
- [x] **Step 3: Implement the function and CLI.** Reuse `validate_repair_handoff` and `FileEvidenceReader`; construct `MySQLTaskStore` directly to avoid schema writes in the read-only CLI. Do not read `case.json`.
- [x] **Step 4: Run the focused tests and `uv run --locked mypy src/project_doctor`.** Passed.
- [x] **Step 5: Commit Task 1 files.** `29714af`.

### Task 2: Separate repair Agent session

**Files:**
- Create: `agh/repair-instructions.md`
- Modify: `agh/diagnosis-instructions.md`
- Test: `tests/integration/agent/test_mcp_protocol.py`

**Interfaces:**
- Consumes: Task 1 handoff and existing MCP `inspect_fix_target`, `read_fix_source`, `submit_fix_patch`, `verify_fix`, `get_fix_status`.
- Produces: a repair session with its own AGH session log and business tool-call log; no new platform Agent loop.

- [x] **Step 1: Add a failing MCP protocol test.** A separate repair Agent must retrieve persisted candidates by task ID.
- [x] **Step 2: Run `uv run --locked pytest -q tests/integration/agent/test_mcp_protocol.py`.** Failed with unknown tool.
- [x] **Step 3: Add `get_repair_handoff` and split diagnosis/repair prompts.** Do not claim N+1 live experiment support until runtime intervention exists.
- [x] **Step 4: Run focused tests.** 19 passed.
- [x] **Step 5: Commit Task 2 files.** `85de18d`.

### Task 3: Export repair facts, never answers

**Files:**
- Modify: `scripts/export_evaluation_run.py`
- Modify: `tests/runtime/test_evaluation_export.py`

**Interfaces:**
- Consumes: original diagnosis export, final `TaskBundle` with `repairs`, separate repair session/tool-call logs, and the existing `RepairRecord.patch_ref`, `comparison`, `baseline_run`, `patched_run`.
- Produces: `attach_repair(payload: dict[str, Any], original: TaskBundle, final: TaskBundle, repair_trace: Path, artifact_root: Path) -> None`; fills `retest.repair` facts and verified `retest` effect fields.

- [ ] **Step 1: Write failing tests.** Cover `retested`, `built`, `failed`, `needs_reconcile`, deliberate no change, absent repair session, mismatched task/finding/commit, corrupt patch, decoy patch location, and unauthorized Finding mutation.
- [ ] **Step 2: Run `uv run --locked pytest -q tests/runtime/test_evaluation_export.py`.** Expect failure.
- [ ] **Step 3: Implement attachment.** Derive `attempted` from repair tool calls or durable records, `patch_present` and changed lines from verified stored unified diff, and `gain_attributable` only from a validated `retested` record. Verify task/finding/image/run/evidence identities. Preserve the original diagnosis report; reject changed Finding fields outside the three approved retest fields.
- [ ] **Step 4: Run focused tests and the dataset evaluator tests.** Expect pass; do not synthesize repair facts from `case.json`.
- [ ] **Step 5: Commit Task 3 files.**

### Task 4: Repeated real handoff acceptance

**Files:**
- Create: `docs/development/acceptance/2026-10-14-diagnosis-repair-handoff.md`
- Modify: `docs/superpowers/plans/2026-10-14-generic-source-repair.md` only for observed status.

**Interfaces:**
- Consumes: Tasks 1-3, AGH CLI, running Docker Linux engine, platform MySQL DSN, `datasets/evaluation/run_eval.py`.
- Produces: at least three independent runs each for case-07 (`expected_to_change=true`) and case-42 (`false`), raw diagnosis/repair traces, final bundles, evaluator input, per-run and aggregate results.

- [ ] **Step 1: Run full tests, Ruff and mypy.** `uv run --locked pytest -q`; `uv run --locked ruff check src scripts tests`; `uv run --locked mypy src/project_doctor`.
- [ ] **Step 2: Check prerequisites.** Record AGH commit/profile reference, Docker `info` Linux engine, MySQL DSN presence (never value), and immutable case source commits. If unavailable, record the exact blocker and do not invent results.
- [ ] **Step 3: Execute six fresh diagnosis sessions.** Capture each persisted task and Finding before starting its separate repair session; no manual insertion of a gold Finding.
- [ ] **Step 4: Execute six repair sessions.** Case-07 must decide whether/where to patch and await diagnosis verdict; case-42 must consider the diagnosis and avoid a patch. Preserve original source and isolated workspace evidence.
- [ ] **Step 5: Export, score and inspect all runs.** Use actual durable repair state and traces. Report decision correctness, target hit, restraint, attributable gain, false verification, repeat pass rate and failures separately. A build or a faster single request is not a verified repair.
- [ ] **Step 6: Save the evidence report and commit it without secrets/runtime dumps.** State each unsupported or unrun path explicitly; do not call the integrated capability accepted unless both positive and negative runs meet the gates.
