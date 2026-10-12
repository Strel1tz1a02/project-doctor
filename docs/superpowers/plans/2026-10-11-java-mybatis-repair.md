# Java/MyBatis N+1 Repair Implementation Plan

> **For agentic workers:** Execute tasks in order. This request uses native execution; do not delegate without the user's approval.

**Goal:** Consume persisted N+1 `BatchQuerySpec`, apply a reviewed Java/MyBatis patch in isolation, and prove a repaired build with an independent correctness and performance retest.

**Architecture:** Repair gates validate the diagnosis handoff and scope. The repair workflow owns patch/build state and delegates effect measurement to the diagnosis retest service. The diagnosis layer owns isolated execution, evidence collection and comparison; repair only backfills a proven verdict.

**Tech Stack:** Python 3.13, Pydantic, MySQL/SQLAlchemy, MCP, Git, Java 17/Maven, Docker Compose, pytest.

**Spec:** `docs/superpowers/specs/2026-10-11-java-mybatis-repair-design.md`

**Implementation status (2026-10-11):** Annotation-based Java/MyBatis patching, durable repair records, MCP tools, diagnosis-owned retest and atomic Recommendation backfill are implemented. The demo patch compiles in Docker. A Docker/MySQL two-image retest reproduced 20 child queries before the patch and 0 after it, with total SQL calls 22 → 3 per request, matching business digests, complete lock evidence and verified restoration. A real persisted Finding → patch → build → diagnosis retest → MySQL backfill chain passed: a noisy run stayed `failed` without changing the Finding; a later run reached `retested` with two three-sample runs and 229 evidence references, while only the three allowed Recommendation fields changed. Verified but rejected measurements are now retained in failed repair records. A prior full suite with Docker and temporary platform MySQL passed 327 tests with 6 skips; two target probes then passed separately. The current focused MCP, MySQL and repair suite passed 22 tests; strict mypy passed 94 source files and Ruff passed. The MCP SDK completed real `verify_fix` and `get_fix_status` calls. The built AGH CLI is at `E:\projects\agnes-harness\packages\cli\dist\local\agnes.mjs`. In a private temporary AGH Home, service ID `pd` connected to the real Project Doctor MCP and reported `ready`, with all 12 tools (including the four repair tools) in its catalog. A longer test service ID caused AGH to reject its generated extension manifest because the tool prefix exceeded its schema length limit. Live model orchestration remains unverified because the AGH Home/model configuration used for this project has not been identified. XML mapper support is deferred.

The repair entry now verifies the original Finding artifacts before source access, and a process-held lease prevents concurrent build/retest replay. When a worker disappears after persisting `preparing` or `retesting`, retrying the same operation conservatively settles it to `needs_reconcile`; no new side effect is started. After these changes, the focused MCP/MySQL/repair suite passed 22 tests, strict mypy passed 95 source files, and Ruff passed. The real Docker/MySQL chain passed again: diagnosis rejected an indistinguishable gain, persisted both three-sample runs and 228 verified evidence references on the `failed` repair, and left the original Finding unchanged.

Recovery now checks the persisted repair ID, finding ID and patch digest before reading current source or handoff artifacts, so a crashed operation can be classified even if those inputs later become unavailable. A real MySQL Store restart test passed, including rejection of a different patch under the same operation ID. The normal Docker/MySQL repair chain passed again after this ordering change; diagnosis again rejected noisy latency gain and retained 228 verified retest references without modifying the Finding.

**2026-10-12 initial verification:** The full suite passed 325 tests with 17 environment skips. With Docker on `PATH`, the real Java image, two-image retest and target-probe group passed 9 tests (2 target-repo-dependent skips). With an isolated temporary MySQL container, the persisted repair chain and both MySQL repair recovery tests passed 3 tests; the container and repair environments were removed afterward. At this stage, the supplied AGH `local-dev` profile resolved, but its provider startup failed with `SECRET_UNRESOLVED` for the `agnes-probe` route, and the existing `pd` MCP row reported `unavailable`. The later acceptance below resolved these gates.

The user supplied the Agnes credential and authorized `pd` connection testing. The credential was stored through AGH's protected credential-store API, and the profile was switched from an unset environment-secret adapter to the managed file adapter. After restarting the AGH daemon, a real Agnes model call returned `OK`. The old case settings lacked timeouts for the four repair tools; after adding them, the authorized `mcp test pd` succeeded and AGH reported `ready` with 12 tools. A subsequent model-to-MCP call carrying internal task and Finding IDs was rejected by automatic approval review because the user's authorization then covered connection testing only. The user later authorized the model-driven calls described below. The credential itself is not stored in this plan or Git-tracked files.

**2026-10-12 AGH read-only acceptance:** The user separately authorized one model-to-MCP `inspect_fix_target` call with the existing Task/Finding IDs. The real Agnes run invoked `mcp_pd_8d1a978e_inspect_fix_target`; the AGH session event log records `tool/call` at sequence 38 and `tool/result` at sequence 42. The tool returned `isError: true` with `only a diagnosed N+1 finding can enter repair`. This historical Finding therefore correctly failed the repair entry gate. AGH connection, model routing, tool discovery, invocation and error propagation are verified. A model-generated patch on a valid N+1 Finding has not been exercised through AGH; the positive patch/build/diagnosis-retest/MySQL chain was verified by the deterministic real Docker/MySQL end-to-end test.

**2026-10-12 patch-gate correction:** The original static patch check accepted any `IN` query anywhere in a mapper file, including a hardcoded `IN (1, 2)` on an unrelated method. It now reads the `@Select` annotation attached to the diagnosed mapper method and requires a parameterized MyBatis `<foreach collection=...>#{...}</foreach>` batch query. The hardcoded counterexample is rejected. Repair tests passed 31 with two Docker-dependent skips in the current shell; Ruff check/format and mypy on the changed source passed. The valid demo patch passed the isolated-source check. The subsequent real Java image build and two-image retest passed after this correction (2 tests in 223.27 seconds).

**2026-10-12 Agnes positive acceptance:** The user authorized sending the isolated demo N+1 Finding and Java source context to Agnes for a full repair run. Agnes proposed and submitted a Java/MyBatis batch-query patch through `pd.submit_fix_patch`; the platform applied it only to an isolated source copy and built distinct baseline/patched image digests. The successful attempt is `repair-7f7c4645c75bb8f4ff09a3c7` (`agh-submit-positive-20261012-v6`, `agh-verify-positive-20261012-v6`). The diagnosis-owned `verify_fix` returned `retested`, and a separate `get_fix_status` read the same durable state. Three baseline samples each had 22 SQL statements with 20 child lookups; three patched samples each had 3 SQL statements with no per-row child lookup. All six business-result checks passed with the same digest. Median latency was 159.983 ms versus 154.512 ms, a measured gain of 3.42%. This supports N+1 elimination but only a modest end-to-end latency improvement in this demo. An earlier model call was interrupted by the Agnes MCP client's 60-second timeout and correctly left `needs_reconcile` without claiming gain; acceptance succeeded only after a temporary, project-local Agnes runtime copy gave both the MCP call and tool execution enough time. That runtime copy was used only for acceptance; the original Agnes installation was not edited.

**2026-10-12 asynchronous MCP amendment:** The user approved changing the model-facing `verify_fix` call to return a durable `retesting` state promptly, with final diagnosis result read through `get_fix_status`. Implement this at the MCP boundary while retaining a synchronous Python workflow for deterministic callers. Keep a strong reference to each running task, coalesce concurrent calls for the same repair, and make the launch acknowledgment wait for the persisted `retesting` transition. Test delayed success, duplicate calls, failure/cancellation recovery, then repeat model-to-MCP acceptance with the original Agnes runtime and its default call timeout.

**2026-10-12 recovery refinement:** The user required reuse of existing diagnosis persistence and recovery rather than a new job platform. MySQL `RepairRecord` remains authoritative; the existing process-held repair lock distinguishes active work from a worker that exited. `get_fix_status` now reconciles abandoned `preparing`/`retesting` records, and the diagnosis adapter closes the two deterministic Docker retest projects for abandoned or failed retests. A durable cleanup-pending marker permits retry after another interruption; no unknown retest is replayed. Focused tests cover active vs exited workers, idempotent cleanup, failure retry, deterministic environment IDs and the asynchronous MCP response. The whole suite passed 333 tests with 17 skips in the unconfigured shell; Docker/MySQL end-to-end repair and repair-store tests passed 3 tests separately with real services. Ruff and strict mypy passed.

## Global Constraints

- Only `n_plus_one` with `BatchQuerySpec.strategy=batch_in` is executable by the first Java/MyBatis adapter.
- Original target source, diagnosis rules, tests, datasets, and original evidence remain immutable.
- A retest runs a newly built image from patched isolated source and records its digest.
- `retested` requires correct business output, controlled comparable samples, SQL-count collapse, verified evidence and restoration.
- The only Finding change on success is the three Recommendation retest fields.

## Review Focus

- Mapper location names an SQL definition, not the service loop: ambiguous callers must stop before patching.
- A plausible diff could change tests or build scripts: path and hunk checks must reject it.
- A rebuilt tag could still point to an old image: assert the recorded image digest and patched source hash.
- Independently seeded environments can differ in snapshot content: reject incomparable snapshots.
- A faster request with changed results or missing lock/restore evidence must not become `retested`.

---

### Task 1: Repair contracts and pure gates

**Files:** Create `src/project_doctor/models/repair.py`, `src/project_doctor/features/repair/gates.py`, `src/project_doctor/features/diagnosis/retest.py`; modify `src/project_doctor/models/finding.py`; test `tests/repair/test_gates.py`.

**Interfaces:** `validate_handoff(finding: Finding, bundle: TaskBundle) -> BatchQuerySpec`; `validate_retest(source: TaskBundle, repaired: TaskBundle, finding: Finding) -> RepairComparison`; `apply_retest_fields(finding: Finding, comparison: RepairComparison) -> Finding`.

- [ ] Write tests for missing `fix_spec`, unsupported strategy, commit/evidence mismatch, changed business results, unstable samples, and only-three-field mutation.
- [ ] Run targeted tests and verify failures.
- [ ] Implement contracts/gates and Recommendation validation so unmeasured states cannot carry retest IDs.
- [ ] Run targeted tests and static checks.

### Task 2: Isolated Java/MyBatis source and patch adapter

**Files:** Create `src/project_doctor/features/repair/source.py`, `src/project_doctor/integrations/repair/source.py`; test `tests/repair/test_source.py`.

**Interfaces:** `inspect_target(root: Path, spec: BatchQuerySpec, commit: str) -> RepairTarget`; `apply_patch(target: RepairTarget, diff: str, workspace_root: Path) -> PatchedSource`.

- [ ] Test mapper identification, unique caller, ambiguous caller, stale commit, path traversal, out-of-scope files and patch context mismatch.
- [ ] Implement read-only source inspection and bounded context with hashes.
- [ ] Implement isolated copy, strict diff validation, `git apply --check`, application and before/after hashes.
- [ ] Run tests and verify target repository bytes are unchanged.

### Task 3: Build and independent retest

**Files:** Create `src/project_doctor/integrations/repair/build.py`, `src/project_doctor/integrations/diagnosis/retest.py`, `src/project_doctor/workflows/diagnose_retest.py`; modify Docker gateway only where necessary to accept immutable image identities; test `tests/repair/test_retest.py` and a Docker-gated integration test.

**Interfaces:** `build_image(source: PatchedSource) -> BuiltImage`; `run_retest(source: TaskBundle, patched: BuiltImage, ...) -> RepairRetest`.

- [ ] Test build failure, digest mismatch, wrong snapshot, business divergence, missing artifacts, failed restore and successful SQL-count collapse.
- [ ] Build with a content-addressed tag from the isolated source and inspect the image digest.
- [ ] Extract the existing HTTP/SQL/lock observation primitive without changing index diagnosis; run baseline-only measurements on old and new images in distinct task environments using the frozen scenario, dataset, warmup and load protocol. The current `RuntimeService.run` and independent retest script are index-only.
- [ ] Verify real Docker/MySQL test when prerequisites are present; record skipped gates accurately.

### Task 4: Durable repair workflow and MCP tools

**Files:** Create `src/project_doctor/workflows/repair.py`; modify `workflows/task_ports.py`, `integrations/mysql/task_store.py`, MySQL schema, `workflows/tools.py`, `entrypoints/bootstrap.py`, `entrypoints/mcp_server.py`, settings/policy; test `tests/repair/test_workflow.py`, MCP protocol and MySQL integration.

**Interfaces:** `inspect_fix_target(context, finding_id) -> RepairTarget`; `submit_fix_patch(context, finding_id, diff) -> RepairRecord`; `verify_fix(context, repair_id) -> RepairRecord`.

- [ ] Test task/finding binding, operation idempotency, unknown execution, concurrent requests, saved patch/artifact references and terminal tasks.
- [ ] Persist repair state before side effects, settle each phase transactionally, and reconcile unknown outcomes.
- [ ] Expose the three tools with explicit timeouts; update AGH instructions and tool policy.
- [ ] Test restart/replay and tool schema compatibility.

### Task 5: Demonstrate complete repair chain

**Files:** Add a Java/MyBatis N+1 fixture under `tests/repair/fixtures/` or use an isolated copy of `demo/slow-query-demo`; add `tests/e2e/test_repair_chain.py`; update repair documentation and exported contracts.

- [ ] Produce a persisted finding and `fix_spec`, inspect mapper/caller, submit a `batch_in` patch, and verify unchanged target source.
- [ ] Compile and run the patched image, compare response digests and SQL counts under matching snapshot/load conditions.
- [ ] Verify failure paths leave `expected_mechanism` and success changes only the three Recommendation fields.
- [ ] Run relevant pytest, Ruff, mypy, schema export, Java build, and real Docker/AGH checks; report any unverified external gate.
