import hashlib
import json
from pathlib import Path

import pytest

from project_doctor.models.common import EvidenceRef
from project_doctor.models.repair import (
    RepairComparison,
    RepairRecord,
    RepairRun,
    RepairSample,
)
from project_doctor.models.task import CallContext, TaskBundle
from project_doctor.workflows.repair_facts import build_repair_facts

PATCH = (
    "diff --git a/src/main/java/com/example/OrderMapper.java "
    "b/src/main/java/com/example/OrderMapper.java\n"
    "--- a/src/main/java/com/example/OrderMapper.java\n"
    "+++ b/src/main/java/com/example/OrderMapper.java\n"
    "@@ -10,2 +10,3 @@ public interface OrderMapper {\n"
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
    (root / name).write_bytes(content.encode("utf-8"))
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


def test_missing_session_stays_unregistered(tmp_path):
    transcript = tmp_path / "s.jsonl"
    transcript.write_text('{"seq":1}\n', encoding="utf-8")
    bundle = load_bundle()
    facts = build_repair_facts(
        bundle,
        artifacts_root=tmp_path,
        repair_session_id=None,
        repair_session_transcript=transcript,
        repair_decision_id="d1",
        finding_id=bundle.findings[0].id,
    )
    # No independent repair session: restraint must not be credited.
    assert facts.handoff is None
    assert facts.repair is None
    assert any("independent" in note for note in facts.notes)


def test_shared_session_stays_unregistered(tmp_path):
    transcript = tmp_path / "s.jsonl"
    transcript.write_text('{"seq":1}\n', encoding="utf-8")
    bundle = load_bundle()
    bundle.task.correlation = CallContext(
        task_id=bundle.task.correlation.task_id,
        operation_id=bundle.task.correlation.operation_id,
        agh_session_id="shared-session",
        missing_correlation=["tool_call_id"],
    )
    facts = build_repair_facts(
        bundle,
        artifacts_root=tmp_path,
        repair_session_id="shared-session",
        repair_session_transcript=transcript,
        repair_decision_id="d1",
        finding_id=bundle.findings[0].id,
    )
    assert facts.handoff is None
    assert facts.repair is None


def test_session_without_transcript_stays_unregistered(tmp_path):
    bundle = load_bundle()
    facts = build_repair_facts(bundle, artifacts_root=tmp_path, repair_session_id="repair-session")
    assert facts.handoff is None
    assert facts.repair is None


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


def test_finding_from_another_task_is_rejected(tmp_path):
    transcript = tmp_path / "s.jsonl"
    transcript.write_text('{"seq":1}\n', encoding="utf-8")
    bundle = load_bundle()
    foreign = bundle.findings[0].model_copy(update={"task_id": "another-task"})
    bundle.findings = [foreign]
    with pytest.raises(ValueError, match="persisted finding"):
        build_repair_facts(
            bundle,
            artifacts_root=tmp_path,
            repair_session_id="repair-session",
            repair_session_transcript=transcript,
            repair_decision_id="d1",
            finding_id=foreign.id,
        )


def test_repair_record_for_foreign_finding_is_rejected(tmp_path):
    bundle = load_bundle()
    bundle.repairs = [record(bundle, "built", tmp_path)]
    bundle.findings = [bundle.findings[0].model_copy(update={"task_id": "another-task"})]
    with pytest.raises(ValueError, match="not persisted"):
        build_repair_facts(bundle, artifacts_root=tmp_path, repair_session_id="repair-session")


def test_non_utf8_patch_artifact_is_reported_as_corrupted(tmp_path):
    bundle = load_bundle()
    stored = record(bundle, "built", tmp_path)
    ref = stored.patch_ref
    assert ref is not None
    raw = b"\xff\xfe\x00not utf-8"
    (tmp_path / "fix.patch").write_bytes(raw)
    stored = stored.model_copy(
        update={
            "patch_ref": ref.model_copy(
                update={"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            )
        }
    )
    bundle.repairs = [stored]
    with pytest.raises(ValueError, match="corrupted"):
        build_repair_facts(bundle, artifacts_root=tmp_path, repair_session_id="repair-session")
