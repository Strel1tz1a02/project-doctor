# Generic Source Repair Implementation Plan

> **For agentic workers:** Implement these tasks sequentially with tests and review each boundary. The user requested no subagents without confirmation; this plan is executed by the current agent.

**Goal:** Make repair inspection, patch execution and durable state independent of N+1, while diagnosis remains the sole authority for source-version retest.

**Architecture:** Reuse the current `RepairWorkflow` and `RepairRecord`. Split common handoff/source-diff policy from the existing MyBatis target checks. Keep `DiagnosisRetestService` as the only verdict path and select a diagnosis-owned verifier by finding kind.

**Tech Stack:** Python 3.13, Pydantic, MCP, Docker/MySQL integration, pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-generic-source-repair-design.md`

## Global Constraints

- Never modify the target checkout, evaluator, tests, diagnostic rules or data through a model patch.
- Missing verifier or incomplete evidence cannot produce `retested` or a measured gain.
- Preserve existing N+1 Docker/MySQL behavior, persistence and recovery.

## Review Focus

- A `lead` with corrupt evidence must be rejected before source inspection.
- A diff touching tests, new files or paths outside the target must be rejected.
- A non-N+1 patch must not be required to match a MyBatis batch-query pattern.
- Unknown verifier, changed business response or noisy gain must retain the original Finding.
- Repeated operation IDs and crashed workers must keep existing idempotency and cleanup semantics.

---

### Task 1: General handoff and source context

**Files:** `features/repair/gates.py`, `models/repair.py`, `integrations/repair/source.py`, `features/repair/source.py`, `tests/repair/test_gates.py`, `tests/repair/test_source.py`.

**Interfaces:** `validate_repair_handoff(finding, bundle) -> Finding`; `inspect_source_target(root, finding, commit) -> SourceRepairTarget`; `present_source_target(finding_id, target) -> CodeRepairTargetView`.

- [x] Add tests for supported handoff kinds, invalid evidence and source identity.
- [x] Implement generic inspection of persisted code locations with file hashes and contexts; keep N+1 extra hints.
- [x] Run focused tests.

### Task 2: Generic isolated patching

**Files:** `integrations/repair/source.py`, `workflows/repair.py`, `tests/repair/test_source.py`, `tests/repair/test_workflow.py`.

**Interfaces:** `apply_source_patch(target, diff, workspace_root) -> PatchedSource`; `copy_baseline_source(target, workspace_root) -> PatchedSource`.

- [x] Test allowed application-source patch and rejected test/config/outside paths; retain common binary/rename restrictions.
- [x] Keep N+1 shape checks in its specific precheck; share content hashing, copy, Git apply, build and record state.
- [x] Run focused tests.

### Task 3: Diagnosis-owned source-version verdict

**Files:** `workflows/diagnose_retest.py`, `features/diagnosis/retest.py`, `integrations/diagnosis/retest.py`, `models/repair.py`, `tests/repair/test_diagnosis_retest.py`.

**Interfaces:** `DiagnosisRetestService.run(bundle, finding, repair) -> ValidatedRetest`; diagnosis validator selection by `Finding.kind`.

- [x] Test shared identity/correctness/evidence gates and unknown-verifier refusal.
- [x] Preserve N+1 validator; add diagnosis-owned slow-query and keyset deep-pagination comparators.
- [x] Run focused tests; Docker-gated tests skip while Docker CLI is unavailable.

### Task 4: Public tools, contracts and acceptance

**Files:** `entrypoints/mcp_server.py`, `workflows/tools.py`, `agh/diagnosis-instructions.md`, `docs/contracts/v0.1`, repair tests.

- [x] Update model-visible target context and instructions; maintain operation-ID idempotency and async status behavior.
- [x] Export schemas and run pytest/Ruff/mypy.
- [ ] Run a real N+1, slow-query and keyset deep-pagination Docker/MySQL chain when Docker CLI and platform DSN are available.
- [x] Record that only N+1 has prior real-chain evidence; newly added verdict paths currently have rule-test evidence.
