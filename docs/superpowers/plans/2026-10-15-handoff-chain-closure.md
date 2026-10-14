# 交接链工程闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 合并执行侧 `codex/diagnosis-repair-handoff` 分支，并从持久化 `TaskBundle.repairs` 自动生成 `handoff.json` / `repair.json` 登记文件，使 main 上已有的一体化评估契约（`handoff` 块 + `retest.repair` 四字段）获得真实数据来源，闭环协作简报 O-1/O-2/O-4。

**Architecture:** main 的 `scripts/export_evaluation_run.py` 已实现「显式登记文件 → 导出器只合并、绝不推断」机制（`load_handoff` / `load_repair`）。本计划**不改导出器**，新增一个登记事实生成器（`workflows/repair_facts.py` + CLI），从持久化 bundle 派生事实、校验后写出登记文件——这是对 spec「字段来源表」的实现路径细化：导出器维持不推断的红线，派生逻辑收敛在独立的、可测试的生成器中。

**Tech Stack:** Python 3.13（`uv run --locked`，本机无系统 python，CPython 一律走 `uv run --no-project --python 3.13 python`）、Pydantic、pytest、纯标准库评测器（`datasets/evaluation/`）。

**Spec:** `docs/superpowers/specs/2026-10-15-handoff-chain-closure-design.md`

## Global Constraints

- 合并出现任何冲突：**停止并报告**，不自动取舍。
- 导出器不读 `case.json`、不推断 handoff/repair 事实（既有红线，本计划不触碰）。
- O-4 收紧：凡存在 `RepairRecord` 即 `attempted=true`；克制路径只在「修复会话 transcript 真实存在且 bundle 无 `RepairRecord`」时产出 `attempted=false` 的 `repair.json`；会话缺席时两个登记文件都不产出。
- `gain_attributable`：`status=="retested"` ∧ `comparison` 非空 ∧ `patched_run` 全部样本 `business_valid` 时为 `true`。
- 金标准零漂移：`GOLDEN_MEAN_TOTAL = 0.8762`、误验证 0、14 例。
- 数据集侧（`datasets/`）保持纯标准库，SUT 源码不得引用 `datasets/`（CI 守卫）。

## File Structure

- `src/project_doctor/features/repair/patch_files.py`（新建）：从 unified diff 解析实际改动行 `[{path, line}]`，纯函数、纯标准库。
- `src/project_doctor/workflows/repair_facts.py`（新建）：`build_repair_facts()` 从 `TaskBundle` 派生 handoff/repair 登记事实，含全部拒绝分支。
- `scripts/register_repair_facts.py`（新建）：CLI，读 run home 的 `bundle.json`，写出/清理 `handoff.json`、`repair.json`。
- `tests/repair/test_patch_files.py`（新建）、`tests/repair/test_repair_facts.py`（新建）、`tests/repair/test_register_cli.py`（新建）。
- `tests/runtime/test_repair_handoff_evaluation.py`（新建）：端到端探针——合成运行包经登记 + 导出后喂给真实评测器。
- `datasets/docs/对接执行测-协作简报.md`（修改）：追加闭环条目、更新 O-1/O-2/O-4 状态。

---

### Task 1: 合并 codex 分支并建立回归基线

**Files:**
- 无新文件；产出为 merge commit。

- [ ] **Step 1: 合并**

```powershell
git merge --no-ff codex/diagnosis-repair-handoff -m "merge: 执行侧诊断-修复交接导出与通用化修复"
```

预期：无冲突自动完成（已用 `git merge-tree` 验证两侧零重叠）。**若出现任何冲突：停止，报告冲突文件清单，不继续。**

- [ ] **Step 2: SUT 静态套件**

```powershell
./scripts/check.ps1
```

预期：pytest 全过、Ruff、mypy（strict）全绿。若失败：修复至全绿再继续（合并引入的真实问题须修，不跳过）。

- [ ] **Step 3: 数据集三守卫 + 评测器单测**

```powershell
cd datasets
uv run --no-project --python 3.13 python tools/validate_cases.py
uv run --no-project --python 3.13 python tools/isolation_guard.py
uv run --no-project --python 3.13 python tools/guard_sut_separation.py
uv run --no-project --python 3.13 python -m unittest discover -s evaluation -p "test_*.py"
uv run --no-project --python 3.13 python -m unittest discover -s tools -p "test_*.py"
cd ..
```

预期：45/45 校验通过、45/45 隔离合规、SUT 分离通过、evaluation/tools 单测全 OK。

- [ ] **Step 4: 金标准不变式**

```powershell
cd datasets
uv run --no-project --python 3.13 python -m unittest evaluation.test_golden_bundle
cd ..
```

预期：`Ran 16 tests ... OK`；`MEAN 0.8762 / N 14 / FALSE_VERIFIED 0`。

- [ ] **Step 5: 提交（merge commit 已完成，此处仅确认）**

```powershell
git log --oneline -3; git status
```

预期：工作区干净，HEAD 为 merge commit。

---

### Task 2: `extract_patch_locations` — unified diff 实际改动行解析

**Files:**
- Create: `src/project_doctor/features/repair/patch_files.py`
- Test: `tests/repair/test_patch_files.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/repair/test_patch_files.py
import pytest

from project_doctor.features.repair.patch_files import extract_patch_locations

DIFF = """diff --git a/src/main/java/com/example/OrderMapper.java b/src/main/java/com/example/OrderMapper.java
index 1111111..2222222 100644
--- a/src/main/java/com/example/OrderMapper.java
+++ b/src/main/java/com/example/OrderMapper.java
@@ -10,7 +10,9 @@ public interface OrderMapper {
     @Select("select * from orders")
     List<Order> findAll();
-    List<User> findById(Long id);
+    List<User> findByIds(@Param("ids") List<Long> ids);
+    // batch variant
     }
@@ -30,4 +32,3 @@ public interface OrderMapper {
     // second hunk
-    void legacy();
+    void legacyRemoved();
"""


def test_added_lines_use_new_side_numbers():
    assert extract_patch_locations(DIFF) == [
        {"path": "src/main/java/com/example/OrderMapper.java", "line": 12},
        {"path": "src/main/java/com/example/OrderMapper.java", "line": 13},
        {"path": "src/main/java/com/example/OrderMapper.java", "line": 33},
    ]


def test_multi_file_and_deletion_only_hunk():
    diff = (
        "diff --git a/a.java b/a.java\n"
        "--- a/a.java\n"
        "+++ b/a.java\n"
        "@@ -5,3 +5,2 @@\n"
        " ctx\n"
        "-old();\n"
        " ctx2\n"
        "diff --git a/b.java b/b.java\n"
        "--- a/b.java\n"
        "+++ b/b.java\n"
        "@@ -7,2 +7,3 @@\n"
        " ctx\n"
        "+newCall();\n"
        " ctx2\n"
    )
    assert extract_patch_locations(diff) == [
        {"path": "a.java", "line": 5},  # deletion-only hunk records the hunk start
        {"path": "b.java", "line": 8},
    ]


def test_empty_diff_rejected():
    with pytest.raises(ValueError, match="empty"):
        extract_patch_locations("   \n")


def test_binary_and_rename_rejected():
    with pytest.raises(ValueError, match="binary"):
        extract_patch_locations(
            "diff --git a/x.bin b/x.bin\nBinary files a/x.bin and b/x.bin differ\n"
        )
    with pytest.raises(ValueError, match="rename"):
        extract_patch_locations(
            "diff --git a/a.java b/b.java\nrename from a.java\nrename to b.java\n"
        )


def test_deleted_file_rejected():
    with pytest.raises(ValueError, match="deletion"):
        extract_patch_locations("diff --git a/a.java b/a.java\n+++ /dev/null\n")


def test_malformed_hunk_rejected():
    with pytest.raises(ValueError, match="hunk"):
        extract_patch_locations("+++ b/a.java\n@@ garbage @@\n+x\n")
```

- [ ] **Step 2: 运行确认失败**

```powershell
uv run --locked pytest -q tests/repair/test_patch_files.py
```

预期：FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现**

```python
# src/project_doctor/features/repair/patch_files.py
"""Extract the source lines a unified diff actually touches (new-file side).

Added lines are recorded at their new-side line number; a hunk that only
removes lines is recorded once at its new-side start. Binary patches, renames
and whole-file deletions are rejected — the repair workflow forbids them.
"""

from __future__ import annotations


def _new_side_start(header: str) -> int:
    try:
        plus = header.split("@@")[1].strip().split()[1]
        return int(plus[1:].split(",")[0])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"malformed hunk header: {header}") from exc


def extract_patch_locations(diff_text: str) -> list[dict[str, object]]:
    if not diff_text.strip():
        raise ValueError("patch diff is empty")
    locations: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()
    path: str | None = None
    new_line = 0
    hunk_start = 0
    hunk_has_add = False
    hunk_has_del = False
    in_hunk = False

    def record(target: str, line: int) -> None:
        key = (target, line)
        if key not in seen:
            seen.add(key)
            locations.append({"path": target, "line": line})

    def flush_hunk() -> None:
        if in_hunk and hunk_has_del and not hunk_has_add and path is not None:
            record(path, hunk_start)

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git"):
            flush_hunk()
            in_hunk, path = False, None
            continue
        if not in_hunk:
            if raw.startswith(("Binary files", "GIT binary patch")):
                raise ValueError("binary patches are not supported")
            if raw.startswith(("rename from", "rename to")):
                raise ValueError("renames are not supported")
            if raw.startswith("+++ "):
                candidate = raw[4:].strip()
                if candidate == "/dev/null":
                    raise ValueError("file deletions are not supported")
                path = candidate[2:] if candidate.startswith("b/") else candidate
                continue
            if raw.startswith("@@ "):
                if path is None:
                    raise ValueError("hunk without a file header")
                new_line = _new_side_start(raw)
                hunk_start, hunk_has_add, hunk_has_del = new_line, False, False
                in_hunk = True
            continue
        if raw.startswith("@@ "):
            flush_hunk()
            new_line = _new_side_start(raw)
            hunk_start, hunk_has_add, hunk_has_del = new_line, False, False
            continue
        if raw.startswith("\\"):
            continue
        if raw.startswith("+"):
            assert path is not None
            record(path, new_line)
            hunk_has_add = True
            new_line += 1
        elif raw.startswith("-"):
            hunk_has_del = True
        else:
            new_line += 1
    flush_hunk()
    if not locations:
        raise ValueError("patch diff touches no source lines")
    return locations
```

- [ ] **Step 4: 运行确认通过 + 类型检查**

```powershell
uv run --locked pytest -q tests/repair/test_patch_files.py
uv run --locked mypy src/project_doctor/features/repair/patch_files.py
```

预期：全 PASS，mypy 无输出。

- [ ] **Step 5: 提交**

```powershell
git add src/project_doctor/features/repair/patch_files.py tests/repair/test_patch_files.py
git commit -m "feat(repair): 从 unified diff 解析补丁实际改动行"
```

---

### Task 3: `build_repair_facts` — 从持久化 bundle 派生登记事实

**Files:**
- Create: `src/project_doctor/workflows/repair_facts.py`
- Test: `tests/repair/test_repair_facts.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/repair/test_repair_facts.py
import hashlib
import json
from pathlib import Path

import pytest

from project_doctor.models.repair import (
    RepairComparison,
    RepairRecord,
    RepairRun,
    RepairSample,
)
from project_doctor.models.common import EvidenceRef
from project_doctor.models.task import TaskBundle
from project_doctor.workflows.repair_facts import build_repair_facts

PATCH = (
    "diff --git a/src/main/java/com/example/OrderMapper.java "
    "b/src/main/java/com/example/OrderMapper.java\n"
    "--- a/src/main/java/com/example/OrderMapper.java\n"
    "+++ b/src/main/java/com/example/OrderMapper.java\n"
    "@@ -10,3 +10,4 @@ public interface OrderMapper {\n"
    "     List<Order> findAll();\n"
    '+    List<User> findByIds(@Param("ids") List<Long> ids);\n'
    "     }\n"
)


def load_bundle() -> TaskBundle:
    path = Path(__file__).parents[1] / "contracts/fixtures/verified_slow_query.json"
    case = json.loads(path.read_text(encoding="utf-8"))
    return TaskBundle.model_validate(case["bundle"])


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def evidence(root: Path, name: str, content: str) -> EvidenceRef:
    (root / name).write_text(content, encoding="utf-8")
    return EvidenceRef(
        artifact_id=name.rsplit(".", 1)[0],
        relative_path=name,
        media_type="text/plain",
        format_version="patch.v1",
        sha256=sha(content),
        size_bytes=len(content.encode()),
    )


def image(tag: int) -> str:
    return "sha256:" + str(tag) * 64


def sample(request: str, valid: bool = True) -> RepairSample:
    return RepairSample(
        request_id=request,
        business_valid=valid,
        result_digest=sha(request),
        latency_ms=10.0,
        sql_count=2,
        child_count=1,
        parent_rows_examined=100,
        parent_keys=["p1"],
        lock_covered=True,
    )


def run(task: str, experiment: str, tag: int, valid: bool = True) -> RepairRun:
    return RepairRun(
        task_id=task,
        experiment_id=experiment,
        source_commit="c" * 40,
        image_digest=image(tag),
        snapshot_id="snap",
        scenario_id="sc",
        scenario_version=1,
        observation_config_id="obs",
        cache_state="warm",
        samples=[sample(f"r{i}", valid) for i in range(3)],
        restored=True,
        artifacts_verified=True,
        evidence_ids=["e1"],
    )


def record(bundle: TaskBundle, status: str, root: Path, *, valid: bool = True) -> RepairRecord:
    patch = evidence(root, "fix.patch", PATCH)
    build = evidence(root, "build.log", "BUILD OK")
    kwargs: dict = {}
    if status in {"built", "retesting", "retested"}:
        kwargs.update(
            source_sha256=sha("src"),
            baseline_source_sha256=sha("base"),
            workspace_name="ws",
            baseline_image_digest=image(1),
            patched_image_digest=image(2),
            patch_ref=patch,
            build_ref=build,
        )
    if status == "retested":
        baseline = run("t-base", "e-base", 1, valid)
        patched = run("t-patched", "e-patched", 2, valid)
        kwargs.update(
            baseline_run=baseline,
            patched_run=patched,
            retest_refs=[build],
            comparison=RepairComparison(
                source_task_id=bundle.task.id,
                finding_id=bundle.findings[0].id,
                baseline_task_id="t-base",
                patched_task_id="t-patched",
                retest_experiment_ids=["e-base", "e-patched"],
                measured_gain_percent=42.0,
                baseline_median_ms=100.0,
                patched_median_ms=58.0,
                evidence_ids=["e1"],
            ),
        )
    if status in {"failed", "needs_reconcile"}:
        kwargs["failure_reason"] = "build broke"
    return RepairRecord(
        id="repair-1",
        task_id=bundle.task.id,
        finding_id=bundle.findings[0].id,
        operation_id="op-1",
        attempt_id="attempt-1",
        status=status,
        source_commit=bundle.task.project.commit,
        patch_sha256=sha(PATCH),
        **kwargs,
    )


def test_no_record_and_no_session_stays_unregistered(tmp_path):
    facts = build_repair_facts(load_bundle(), artifacts_root=tmp_path, repair_session_id=None)
    assert facts.handoff is None and facts.repair is None


def test_restraint_requires_an_auditable_session(tmp_path):
    transcript = tmp_path / "repair-session.jsonl"
    transcript.write_text('{"seq":1}\n', encoding="utf-8")
    bundle = load_bundle()
    facts = build_repair_facts(
        bundle,
        artifacts_root=tmp_path,
        repair_session_id="repair-session",
        repair_session_transcript=transcript,
        repair_decision_id="decision-1",
        finding_id=bundle.findings[0].id,
    )
    assert facts.repair == {
        "attempted": False,
        "patch_present": False,
        "patch_files": [],
        "gain_attributable": False,
    }
    assert facts.handoff["repair_id"] == "decision-1"
    assert facts.handoff["build_result"] == "skipped"
    assert facts.handoff["finding_from_this_run"] is True


def test_restraint_rejects_a_finding_from_outside_this_task(tmp_path):
    transcript = tmp_path / "s.jsonl"
    transcript.write_text('{"seq":1}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="persisted finding"):
        build_repair_facts(
            load_bundle(),
            artifacts_root=tmp_path,
            repair_session_id="s2",
            repair_session_transcript=transcript,
            repair_decision_id="d1",
            finding_id="preset-finding",
        )


def test_same_session_omits_handoff_but_keeps_repair(tmp_path):
    transcript = tmp_path / "s.jsonl"
    transcript.write_text('{"seq":1}\n', encoding="utf-8")
    bundle = load_bundle()
    facts = build_repair_facts(
        bundle,
        artifacts_root=tmp_path,
        repair_session_id=bundle.task.correlation.agh_session_id,
        repair_session_transcript=transcript,
        repair_decision_id="d1",
        finding_id=bundle.findings[0].id,
    )
    assert facts.handoff is None
    assert facts.repair["attempted"] is False
    assert any("independent" in note for note in facts.notes)


def test_built_patch_exports_actual_lines_and_build_ok(tmp_path):
    bundle = load_bundle()
    bundle.repairs = [record(bundle, "built", tmp_path)]
    facts = build_repair_facts(bundle, artifacts_root=tmp_path, repair_session_id="repair-session")
    assert facts.repair["attempted"] is True
    assert facts.repair["patch_present"] is True
    assert facts.repair["patch_files"] == [
        {"path": "src/main/java/com/example/OrderMapper.java", "line": 11}
    ]
    assert facts.repair["gain_attributable"] is False
    assert facts.handoff["build_result"] == "ok"
    assert facts.handoff["repair_id"] == "repair-1"


def test_retested_with_business_valid_samples_marks_gain_attributable(tmp_path):
    bundle = load_bundle()
    bundle.repairs = [record(bundle, "retested", tmp_path)]
    facts = build_repair_facts(bundle, artifacts_root=tmp_path, repair_session_id="repair-session")
    assert facts.repair["gain_attributable"] is True


def test_retested_with_broken_business_result_is_not_attributable(tmp_path):
    bundle = load_bundle()
    bundle.repairs = [record(bundle, "retested", tmp_path, valid=False)]
    facts = build_repair_facts(bundle, artifacts_root=tmp_path, repair_session_id="repair-session")
    assert facts.repair["gain_attributable"] is False


def test_failed_build_maps_to_failed_and_no_patch(tmp_path):
    bundle = load_bundle()
    bundle.repairs = [record(bundle, "failed", tmp_path)]
    facts = build_repair_facts(bundle, artifacts_root=tmp_path, repair_session_id="repair-session")
    assert facts.repair["attempted"] is True
    assert facts.repair["patch_present"] is False
    assert facts.handoff["build_result"] == "failed"


def test_commit_task_and_finding_mismatch_rejected(tmp_path):
    bundle = load_bundle()
    other = record(bundle, "built", tmp_path).model_copy(update={"source_commit": "0" * 40})
    bundle.repairs = [other]
    with pytest.raises(ValueError, match="commit"):
        build_repair_facts(bundle, artifacts_root=tmp_path, repair_session_id="s2")


def test_corrupt_patch_artifact_rejected(tmp_path):
    bundle = load_bundle()
    bundle.repairs = [record(bundle, "built", tmp_path)]
    (tmp_path / "fix.patch").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupted"):
        build_repair_facts(bundle, artifacts_root=tmp_path, repair_session_id="s2")


def test_multiple_records_rejected(tmp_path):
    bundle = load_bundle()
    bundle.repairs = [record(bundle, "built", tmp_path), record(bundle, "built", tmp_path)]
    with pytest.raises(ValueError, match="multiple"):
        build_repair_facts(bundle, artifacts_root=tmp_path, repair_session_id="s2")
```

- [ ] **Step 2: 运行确认失败**

```powershell
uv run --locked pytest -q tests/repair/test_repair_facts.py
```

预期：FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现**

```python
# src/project_doctor/workflows/repair_facts.py
"""Derive handoff/repair registration facts from a persisted task bundle.

The evaluation exporter (``scripts/export_evaluation_run.py``) only merges
explicitly registered ``handoff.json`` / ``repair.json`` files and never
infers them. This module is the single place that turns durable repair state
into those registrations, with hard refusals instead of half-facts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from project_doctor.features.repair.patch_files import extract_patch_locations
from project_doctor.integrations.artifacts.verify import resolve_contained
from project_doctor.models.repair import RepairRecord
from project_doctor.models.task import TaskBundle

PATCH_SUCCESS_STATES = {"built", "retesting", "retested"}


@dataclass(frozen=True)
class RepairFacts:
    handoff: dict[str, object] | None
    repair: dict[str, object] | None
    notes: tuple[str, ...] = field(default=())


def _patch_text(root: Path, record: RepairRecord) -> str:
    ref = record.patch_ref
    assert ref is not None  # guarded by the caller's patch_present check
    try:
        raw = resolve_contained(root, ref.relative_path).read_bytes()
    except (OSError, ValueError) as exc:
        raise ValueError("patch artifact is missing or corrupted") from exc
    if len(raw) != ref.size_bytes or hashlib.sha256(raw).hexdigest() != ref.sha256:
        raise ValueError("patch artifact is missing or corrupted")
    return raw.decode("utf-8")


def build_repair_facts(
    bundle: TaskBundle,
    *,
    artifacts_root: Path,
    repair_session_id: str | None,
    repair_session_transcript: Path | None = None,
    repair_decision_id: str | None = None,
    finding_id: str | None = None,
) -> RepairFacts:
    diagnosis_session_id = bundle.task.correlation.agh_session_id or ""
    notes: list[str] = []

    def handoff(repair_id: str, finding: str, build_result: str) -> dict[str, object] | None:
        if not repair_session_id or repair_session_id == diagnosis_session_id:
            notes.append("repair session is missing or not independent; handoff omitted")
            return None
        return {
            "task_id": bundle.task.id,
            "finding_id": finding,
            "repair_id": repair_id,
            "source_commit": bundle.task.project.commit,
            "diagnosis_session_id": diagnosis_session_id,
            "repair_session_id": repair_session_id,
            "finding_from_this_run": True,
            "build_result": build_result,
        }

    if not bundle.repairs:
        # Restraint path: a no-change decision is auditable only with a real repair session.
        if (
            repair_session_transcript is None
            or not repair_session_transcript.is_file()
            or not repair_session_transcript.read_text(encoding="utf-8", errors="replace").strip()
        ):
            return RepairFacts(handoff=None, repair=None)
        repair = {
            "attempted": False,
            "patch_present": False,
            "patch_files": [],
            "gain_attributable": False,
        }
        if repair_decision_id is None:
            notes.append("no repair decision id; handoff omitted")
            return RepairFacts(handoff=None, repair=repair, notes=tuple(notes))
        if finding_id is None or finding_id not in {f.id for f in bundle.findings}:
            raise ValueError("no-change handoff requires a persisted finding from this task")
        return RepairFacts(
            handoff=handoff(repair_decision_id, finding_id, "skipped"),
            repair=repair,
            notes=tuple(notes),
        )

    if len(bundle.repairs) != 1:
        raise ValueError("multiple repair records are not supported yet")
    record = bundle.repairs[0]
    if record.task_id != bundle.task.id:
        raise ValueError("repair record belongs to another task")
    if record.finding_id not in {f.id for f in bundle.findings}:
        raise ValueError("repair finding is not persisted in this task")
    if record.source_commit != bundle.task.project.commit:
        raise ValueError("repair source commit differs from the diagnosed commit")

    patch_present = bool(record.patch_ref and record.status in PATCH_SUCCESS_STATES)
    patch_files = (
        extract_patch_locations(_patch_text(artifacts_root, record)) if patch_present else []
    )
    build_result = "ok" if record.build_ref is not None and record.status != "failed" else "failed"
    gain = bool(
        record.status == "retested"
        and record.comparison is not None
        and record.patched_run is not None
        and all(sample.business_valid for sample in record.patched_run.samples)
    )
    return RepairFacts(
        handoff=handoff(record.id, record.finding_id, build_result),
        repair={
            "attempted": True,
            "patch_present": patch_present,
            "patch_files": patch_files,
            "gain_attributable": gain,
        },
        notes=tuple(notes),
    )
```

- [ ] **Step 4: 运行确认通过 + mypy**

```powershell
uv run --locked pytest -q tests/repair/test_repair_facts.py tests/repair/test_patch_files.py
uv run --locked mypy src/project_doctor
```

预期：全 PASS，mypy 全绿。

- [ ] **Step 5: 提交**

```powershell
git add src/project_doctor/workflows/repair_facts.py tests/repair/test_repair_facts.py
git commit -m "feat: 从持久化修复状态派生 handoff/repair 登记事实"
```

---

### Task 4: CLI `scripts/register_repair_facts.py`

**Files:**
- Create: `scripts/register_repair_facts.py`
- Test: `tests/repair/test_register_cli.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/repair/test_register_cli.py
import json
from pathlib import Path

from project_doctor.models.task import TaskBundle
from scripts.register_repair_facts import main


def make_home(path: Path) -> TaskBundle:
    case = json.loads(
        (Path(__file__).parents[1] / "contracts/fixtures/verified_slow_query.json").read_text(
            encoding="utf-8"
        )
    )
    bundle = TaskBundle.model_validate(case["bundle"])
    path.mkdir()
    (path / "bundle.json").write_text(bundle.model_dump_json(), encoding="utf-8")
    return bundle


def test_cli_writes_and_clears_registration_files(tmp_path, monkeypatch):
    home = tmp_path / "home"
    bundle = make_home(home)
    transcript = tmp_path / "repair-session.jsonl"
    transcript.write_text('{"seq":1}\n', encoding="utf-8")
    argv = [
        "register_repair_facts",
        "--home",
        str(home),
        "--repair-session-id",
        "repair-session",
        "--repair-session-transcript",
        str(transcript),
        "--repair-decision-id",
        "decision-1",
        "--finding-id",
        bundle.findings[0].id,
    ]
    monkeypatch.setattr("sys.argv", argv)
    main()
    handoff = json.loads((home / "handoff.json").read_text(encoding="utf-8"))
    repair = json.loads((home / "repair.json").read_text(encoding="utf-8"))
    assert handoff["repair_id"] == "decision-1"
    assert repair["attempted"] is False
    # A later run without session evidence clears stale registrations.
    monkeypatch.setattr("sys.argv", ["register_repair_facts", "--home", str(home)])
    main()
    assert not (home / "handoff.json").exists()
    assert not (home / "repair.json").exists()
```

- [ ] **Step 2: 运行确认失败**

```powershell
uv run --locked pytest -q tests/repair/test_register_cli.py
```

预期：FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现**

```python
# scripts/register_repair_facts.py
"""Write handoff.json / repair.json for one run home from its persisted bundle.

Run this before ``export_evaluation_run.py``; the exporter only merges the
registered files and never infers them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from project_doctor.models.task import TaskBundle
from project_doctor.workflows.repair_facts import build_repair_facts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--artifacts-root", type=Path, default=None)
    parser.add_argument("--repair-session-id", default=None)
    parser.add_argument("--repair-session-transcript", type=Path, default=None)
    parser.add_argument("--repair-decision-id", default=None)
    parser.add_argument("--finding-id", default=None)
    args = parser.parse_args()
    home: Path = args.home
    bundle = TaskBundle.model_validate_json((home / "bundle.json").read_text(encoding="utf-8"))
    facts = build_repair_facts(
        bundle,
        artifacts_root=args.artifacts_root or home / "artifacts",
        repair_session_id=args.repair_session_id,
        repair_session_transcript=args.repair_session_transcript,
        repair_decision_id=args.repair_decision_id,
        finding_id=args.finding_id,
    )
    for name, payload in (("handoff.json", facts.handoff), ("repair.json", facts.repair)):
        target = home / name
        if payload is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for note in facts.notes:
        print(f"note: {note}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过**

```powershell
uv run --locked pytest -q tests/repair/test_register_cli.py tests/repair/
```

预期：全 PASS。

- [ ] **Step 5: 提交**

```powershell
git add scripts/register_repair_facts.py tests/repair/test_register_cli.py
git commit -m "feat: 登记事实 CLI（写出/清理 handoff.json 与 repair.json）"
```

---

### Task 5: 端到端探针——合成运行包经真实评测器判定

**Files:**
- Test: `tests/runtime/test_repair_handoff_evaluation.py`

探针用既有 fixture bundle 合成两个 run home（应修 / 克制），走「登记 → 导出 → 真实评测器」全链，断言 `handoff_valid` 闸门与修复四项的产出值。本探针不断言用例整体通过（合成包未含独立复测层与 case-44 真实缺陷结构，其他闸门不属本计划范围）。

> 注意：`tests/runtime/` 无 `__init__.py`，不能跨测试文件 import；本探针**完全自包含**（本地复制 `make_home` 与 record 构造器），不 import `tests.runtime` / `tests.repair` 的成员。

- [ ] **Step 1: 写探针测试**

```python
# tests/runtime/test_repair_handoff_evaluation.py
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from project_doctor.features.reports.build import build_report
from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.models.common import EvidenceRef
from project_doctor.models.experiment import ExperimentSpec
from project_doctor.models.finding import ReportResult
from project_doctor.models.repair import RepairRecord
from project_doctor.models.task import TaskBundle
from project_doctor.workflows.repair_facts import build_repair_facts
from scripts.export_evaluation_run import export_run

ROOT = Path(__file__).parents[2]
TARGET = "src/main/java/com/example/slowquery/service/ArticleService.java"
AIMED_PATCH = (
    "diff --git a/" + TARGET + " b/" + TARGET + "\n"
    "--- a/" + TARGET + "\n"
    "+++ b/" + TARGET + "\n"
    "@@ -29,3 +29,4 @@ public class ArticleService {\n"
    "         List<Article> articles = articleMapper.findRecent(size);\n"
    "+        List<Author> authors = authorMapper.findByIds(authorIds);\n"
    "         return articles;\n"
)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_bundle(status: str) -> TaskBundle:
    case = json.loads(
        (ROOT / "tests/contracts/fixtures/verified_slow_query.json").read_text(encoding="utf-8")
    )
    bundle = TaskBundle.model_validate(case["bundle"])
    bundle.experiments[0].spec = ExperimentSpec.model_validate(case["spec"])
    bundle.task.status = "completed"
    for finding in bundle.findings:
        finding.status = status
    return bundle


def make_home(path: Path, bundle: TaskBundle) -> Path:
    path.mkdir()
    root = path / "artifacts"
    report = build_report(bundle)

    async def publish():
        refs = []
        for name, content, media in (
            ("report.json", report.json_content, "application/json"),
            ("report.html", report.html_content, "text/html"),
        ):
            refs.append(await publish_artifact(root, name, content.encode(), media, "report.v1"))
        return refs

    refs = asyncio.run(publish())
    result = ReportResult(
        task_id=bundle.task.id, task_status=bundle.task.status, json_ref=refs[0], html_ref=refs[1]
    )
    (path / "bundle.json").write_text(bundle.model_dump_json(), encoding="utf-8")
    (path / "finish_task-latest.json").write_text(result.model_dump_json(), encoding="utf-8")
    (path / "business-tool-calls.jsonl").write_text(
        json.dumps(
            {
                "name": "finish_task",
                "args": [{"task_id": bundle.task.id}],
                "result": result.model_dump(mode="json"),
                "started_at": 100,
                "ended_at": 101,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (path / "session.jsonl").write_text('{"seq":1,"type":"tool"}\n', encoding="utf-8")
    return path


def evidence(root: Path, name: str, content: str) -> EvidenceRef:
    (root / name).write_text(content, encoding="utf-8")
    return EvidenceRef(
        artifact_id=name.rsplit(".", 1)[0],
        relative_path=name,
        media_type="text/plain",
        format_version="patch.v1",
        sha256=sha(content),
        size_bytes=len(content.encode()),
    )


def image(tag: int) -> str:
    return "sha256:" + str(tag) * 64


def aimed_record(bundle: TaskBundle, root: Path) -> RepairRecord:
    return RepairRecord(
        id="repair-1",
        task_id=bundle.task.id,
        finding_id=bundle.findings[0].id,
        operation_id="op-1",
        attempt_id="attempt-1",
        status="built",
        source_commit=bundle.task.project.commit,
        patch_sha256=sha(AIMED_PATCH),
        source_sha256=sha("src"),
        baseline_source_sha256=sha("base"),
        workspace_name="ws",
        baseline_image_digest=image(1),
        patched_image_digest=image(2),
        patch_ref=evidence(root, "fix.patch", AIMED_PATCH),
        build_ref=evidence(root, "build.log", "BUILD OK"),
    )


def register(home: Path, bundle: TaskBundle, **kwargs) -> None:
    facts = build_repair_facts(
        bundle, artifacts_root=home / "artifacts", repair_session_id="repair-session", **kwargs
    )
    if facts.handoff is not None:
        (home / "handoff.json").write_text(json.dumps(facts.handoff), encoding="utf-8")
    if facts.repair is not None:
        (home / "repair.json").write_text(json.dumps(facts.repair), encoding="utf-8")


def case44_payload(tmp_path: Path) -> dict:
    bundle = load_bundle("verified")
    home = make_home(tmp_path / "home44", bundle)
    bundle.repairs = [aimed_record(bundle, home / "artifacts")]
    (home / "bundle.json").write_text(bundle.model_dump_json(), encoding="utf-8")
    register(home, bundle)
    return export_run(home, "case-44-n-plus-one-article-author")


def case46_payload(tmp_path: Path) -> dict:
    bundle = load_bundle("lead")
    home = make_home(tmp_path / "home46", bundle)
    transcript = tmp_path / "repair-session.jsonl"
    transcript.write_text('{"seq":1,"type":"tool"}\n', encoding="utf-8")
    register(
        home,
        bundle,
        repair_session_transcript=transcript,
        repair_decision_id="decision-1",
        finding_id=bundle.findings[0].id,
    )
    return export_run(home, "case-46-n-plus-one-out-of-bounds-stop")


def evaluate(runs: Path, out: Path) -> dict:
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "datasets/evaluation/run_eval.py"),
            "--runs",
            str(runs),
            "--out",
            str(out),
            "--cases-root",
            str(ROOT / "datasets"),
            "--only-bundled",
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def scores(report: dict, case_id: str) -> dict:
    row = next(c for c in report["cases"] if c["case_id"] == case_id)
    return {
        "gates_failed": row["failed_gates"],
        **{s["name"]: s["value"] for s in row["scores"]},
    }


@pytest.fixture(scope="module")
def report(tmp_path_factory) -> dict:
    tmp_path = tmp_path_factory.mktemp("handoff-eval")
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "case-44-n-plus-one-article-author.json").write_text(
        json.dumps(case44_payload(tmp_path), ensure_ascii=False), encoding="utf-8"
    )
    (runs / "case-46-n-plus-one-out-of-bounds-stop.json").write_text(
        json.dumps(case46_payload(tmp_path), ensure_ascii=False), encoding="utf-8"
    )
    return evaluate(runs, tmp_path / "out")


def test_case44_handoff_and_repair_wiring(report):
    scores44 = scores(report, "case-44-n-plus-one-article-author")
    assert scores44["handoff_valid"] is True
    assert scores44["repair_warranted"] is True
    assert scores44["repair_target_hit"] is True
    # 合成包未跑独立复测层：无实测收益 → 不归因、不计修复成功（诚实输出，非本计划缺口）。
    assert scores44["gain_attributable"] is False
    assert "repair_restraint" in scores44["gates_failed"]


def test_case46_restraint_with_valid_handoff(report):
    scores46 = scores(report, "case-46-n-plus-one-out-of-bounds-stop")
    assert scores46["handoff_valid"] is True
    assert scores46["repair_warranted"] is True
    assert scores46["repair_target_hit"] is True
    assert scores46["repair_restraint"] is True
    assert scores46["gain_attributable"] is True


def test_tampered_handoff_fails_the_gate(tmp_path: Path):
    payload = case46_payload(tmp_path)
    payload["handoff"]["finding_from_this_run"] = False
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "case-46-n-plus-one-out-of-bounds-stop.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    row = scores(evaluate(runs, tmp_path / "out"), "case-46-n-plus-one-out-of-bounds-stop")
    assert row["handoff_valid"] is False
    assert "handoff_valid" in row["gates_failed"]
```

> 关键行号：`AIMED_PATCH` 的 hunk 头 `@@ -29,3 +29,4 @@` 表示 new-side 从 29 起——上下文行 29、新增行 30，故 `patch_files = [{path: TARGET, line: 30}]`，与 case-44 期望缺陷位置 `ArticleService.java:32` 在默认 ±5 容差内命中 `repair_target_hit`。

- [ ] **Step 2: 运行探针**

```powershell
uv run --locked pytest -q tests/runtime/test_repair_handoff_evaluation.py
```

预期：3 个测试全 PASS。若评测器字段名与断言不符（如 `failed_gates` 结构差异），按 `out/report.json` 实际结构调整断言键名，不得改评测器。

- [ ] **Step 3: 提交**

```powershell
git add tests/runtime/test_repair_handoff_evaluation.py
git commit -m "test: 交接链端到端探针（登记→导出→真实评测器闸门）"
```

---

### Task 6: 协作简报闭环 + 最终回归

**Files:**
- Modify: `datasets/docs/对接执行测-协作简报.md`

- [ ] **Step 1: 追加闭环条目**

在「§4 信息交换记录」末尾追加：

```markdown
### [9] 2026-10-15 · 数据集侧 · 执行侧交接登记落地，`O-1`/`O-2`/`O-4` 闭环

- **结论**：执行侧分支 `codex/diagnosis-repair-handoff` 已合并入 main；新增登记事实生成器
  `workflows/repair_facts.py` + CLI `scripts/register_repair_facts.py`，从持久化
  `TaskBundle.repairs` 派生 `handoff.json` / `repair.json`；导出器维持「只合并登记文件、
  绝不推断」红线不变。端到端探针（合成运行包 → 真实评测器）验证 case-44/46 的
  `handoff_valid` 闸门与修复四项产出正确。
- **依据**：`tests/repair/test_repair_facts.py`、`tests/repair/test_register_cli.py`、
  `tests/runtime/test_repair_handoff_evaluation.py` 全绿；`patch_files` 自补丁 diff 解析
  实际改动行（`features/repair/patch_files.py`）。
- **影响面**：`src/project_doctor/`（新增 2 模块）、`scripts/`（新增 1 CLI）、`tests/`；
  评测契约字段**无增删**。
- **请求对方**：无需动作（执行侧即本仓）。
- **状态**：`已闭环`
```

把「§5 开放事项」表中 `O-1`、`O-2`、`O-4` 的状态改为 `已闭环`：

- `O-1`：`已闭环`（四字段由 `register_repair_facts` 自持久化 bundle 派生；`patch_files` 解析自补丁 diff 实际改动行；`gain_attributable` 由执行侧按复测事实显式标注）
- `O-2`：`已闭环`（平铺 `[{path, line}]`，来源 = 补丁 diff 解析，非期望位置冒充）
- `O-4`：`已闭环`（收紧：凡存在 `RepairRecord` 即 `attempted=true`；克制只认「修复会话 transcript 存在且无 RepairRecord」）

在「§6 变更历史」追加一行：

```markdown
| 2026-10-15 | 追加 §4 条目 [9]：执行侧交接登记落地，`O-1`/`O-2`/`O-4` 闭环。 |
```

- [ ] **Step 2: 最终全量回归**

```powershell
./scripts/check.ps1
cd datasets
uv run --no-project --python 3.13 python tools/validate_cases.py
uv run --no-project --python 3.13 python tools/isolation_guard.py
uv run --no-project --python 3.13 python tools/guard_sut_separation.py
uv run --no-project --python 3.13 python -m unittest evaluation.test_golden_bundle
cd ..
```

预期：全绿；金标准 `MEAN 0.8762 / N 14 / FALSE_VERIFIED 0` 不变。

- [ ] **Step 3: 提交**

```powershell
git add datasets/docs/对接执行测-协作简报.md
git commit -m "docs(datasets): 执行侧交接登记落地，O-1/O-2/O-4 闭环"
```

---

## Self-Review 记录

- **Spec 覆盖**：合并（T1）、`handoff` 块（T3/T4 产出登记文件，导出器既有合并逻辑）、`retest.repair` 四字段（T2 解析 + T3 派生）、协作简报闭环（T6）、端到端验证含克制与反例（T5）、回归（T1/T6）——全覆盖。实现路径细化：spec 的「字段来源表」由新组件 `repair_facts` 落地，导出器不改（其 `load_handoff`/`load_repair` 已存在于 main）。
- **类型一致性**：`build_repair_facts` 的关键字参数与 CLI 参数一一对应；`RepairFacts.handoff/repair/notes` 在 T3 定义、T4/T5 消费，名称一致；`extract_patch_locations` 返回 `[{path, line}]` 与评测器平铺格式一致。
- **已知边界**：多 `RepairRecord` 任务暂拒绝（YAGNI，后续需要时再定消歧规则）；`case-44` 探针不断言整体通过（合成包无独立复测层，已在测试中注明）。
