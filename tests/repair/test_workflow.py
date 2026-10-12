"""Patch workflow accepts diagnosis verdicts; it never invents measurements."""

import asyncio
import hashlib
from pathlib import Path

import pytest

from project_doctor.entrypoints.settings import Settings
from project_doctor.features.diagnosis.retest import evaluate_retest
from project_doctor.models.common import EvidenceRef
from project_doctor.models.repair import RepairRecord
from project_doctor.workflows.diagnose_retest import (
    RetestEvidence,
    RetestRejected,
    ValidatedRetest,
)
from project_doctor.workflows.repair import RepairWorkflow
from tests.diagnosis.test_n_plus_one import Reader
from tests.repair.test_diagnosis_retest import _ref, _repair
from tests.repair.test_gates import _handoff, _run


class Store:
    def __init__(self, bundle, repair) -> None:
        self.bundle = bundle
        self.repair = repair

    async def load_bundle(self, task_id):
        assert task_id == self.bundle.task.id
        return self.bundle

    async def load_repair(self, task_id, repair_id):
        assert task_id == self.bundle.task.id
        return self.repair if repair_id == self.repair.id else None

    async def create_repair(self, repair):
        return self.repair

    async def update_repair(self, repair, expected_status):
        if self.repair.status != expected_status:
            return False
        self.repair = repair
        return True

    async def complete_repair(self, repair, finding, expected_status):
        if self.repair.status != expected_status:
            return False
        self.repair = repair
        self.bundle.findings = [finding]
        return True


class Diagnosis:
    def __init__(self, finding, *, fail: bool = False) -> None:
        self.finding = finding
        self.fail = fail
        self.calls = 0
        self.cleanups = 0

    async def cleanup(self, repair, context):
        self.cleanups += 1

    async def run(self, bundle, finding, repair):
        self.calls += 1
        assert repair.status == "retesting"
        if self.fail:
            raise ValueError("diagnostic comparison failed")
        baseline, patched = _run(), _run(patched=True)
        comparison = evaluate_retest(self.finding, baseline, patched)
        refs = tuple(
            EvidenceRef(
                artifact_id=artifact_id,
                relative_path=f"repairs/{artifact_id}.json",
                media_type="application/json",
                format_version="repair.run.v1",
                sha256="a" * 64,
                size_bytes=1,
            )
            for artifact_id in comparison.evidence_ids
        )
        return ValidatedRetest(comparison, RetestEvidence(baseline, patched, refs))


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        platform_dsn_ref="env:PLATFORM_DSN",
        artifact_root=tmp_path / "artifacts",
        workspace_root=tmp_path / "workspaces",
        target_repo_root=tmp_path / "target",
        allowed_target_network="127.0.0.0/8",
        tool_timeouts={"verify_fix": 60},
        model_config_ref="file:model.json",
    )


def test_workflow_backfills_only_after_diagnosis_verdict(tmp_path: Path) -> None:
    bundle, finding = _handoff()
    repair = _repair(bundle, finding).model_copy(update={"status": "built"})
    store = Store(bundle, repair)
    diagnosis = Diagnosis(finding)
    workflow = RepairWorkflow(_settings(tmp_path), store, Reader(), diagnosis)
    completed = asyncio.run(workflow.verify_fix(bundle.task.correlation, repair.id))
    assert completed.status == "retested"
    assert bundle.findings[0].recommendation.validation_status == "retested"
    assert diagnosis.calls == 1
    assert asyncio.run(workflow.verify_fix(bundle.task.correlation, repair.id)) == completed
    assert diagnosis.calls == 1


def test_workflow_keeps_recommendation_unretested_on_diagnostic_failure(tmp_path: Path) -> None:
    bundle, finding = _handoff()
    repair = _repair(bundle, finding).model_copy(update={"status": "built"})
    store = Store(bundle, repair)
    workflow = RepairWorkflow(_settings(tmp_path), store, Reader(), Diagnosis(finding, fail=True))
    with pytest.raises(ValueError, match="diagnostic comparison failed"):
        asyncio.run(workflow.verify_fix(bundle.task.correlation, repair.id))
    assert store.repair.status == "failed"
    assert bundle.findings[0].recommendation.validation_status == "expected_mechanism"


def test_workflow_refuses_corrupt_diagnostic_handoff_before_source_access(
    tmp_path: Path,
) -> None:
    bundle, finding = _handoff()
    repair = _repair(bundle, finding).model_copy(update={"status": "built"})
    workflow = RepairWorkflow(
        _settings(tmp_path), Store(bundle, repair), Reader(False), Diagnosis(finding)
    )
    with pytest.raises(ValueError, match="handoff evidence"):
        asyncio.run(workflow.inspect_fix_target(bundle.task.correlation, finding.id))


def test_workflow_persists_rejected_diagnosis_samples(tmp_path: Path) -> None:
    bundle, finding = _handoff()
    repair = _repair(bundle, finding).model_copy(update={"status": "built"})
    store = Store(bundle, repair)
    evidence = RetestEvidence(_run(), _run(patched=True), (_ref(),))

    class RejectedDiagnosis:
        async def run(self, bundle, finding, repair):
            raise RetestRejected("gain is indistinguishable", evidence)

        async def cleanup(self, repair, context):
            pass

    workflow = RepairWorkflow(_settings(tmp_path), store, Reader(), RejectedDiagnosis())
    with pytest.raises(RetestRejected, match="gain"):
        asyncio.run(workflow.verify_fix(bundle.task.correlation, repair.id))
    assert store.repair.status == "failed"
    assert store.repair.baseline_run == evidence.baseline
    assert store.repair.patched_run == evidence.patched
    assert store.repair.retest_refs == list(evidence.refs)
    assert bundle.findings[0] == finding


def test_retesting_left_by_exited_worker_becomes_unknown_without_replay(tmp_path: Path) -> None:
    bundle, finding = _handoff()
    repair = _repair(bundle, finding)
    store = Store(bundle, repair)
    diagnosis = Diagnosis(finding)
    workflow = RepairWorkflow(_settings(tmp_path), store, Reader(), diagnosis)
    result = asyncio.run(workflow.verify_fix(bundle.task.correlation, repair.id))
    assert result.status == "needs_reconcile"
    assert "exited" in (result.failure_reason or "")
    assert diagnosis.calls == 0
    assert diagnosis.cleanups == 1
    assert bundle.findings[0] == finding


def test_status_reconciles_exited_retest_and_cleans_once(tmp_path: Path) -> None:
    bundle, finding = _handoff()
    repair = _repair(bundle, finding)
    store = Store(bundle, repair)
    diagnosis = Diagnosis(finding)
    workflow = RepairWorkflow(_settings(tmp_path), store, Reader(), diagnosis)
    result = asyncio.run(workflow.get_fix_status(bundle.task.correlation, repair.id))
    assert result.status == "needs_reconcile"
    assert diagnosis.cleanups == 1
    assert asyncio.run(workflow.get_fix_status(bundle.task.correlation, repair.id)) == result
    assert diagnosis.cleanups == 1


def test_status_keeps_active_retest_running(tmp_path: Path) -> None:
    bundle, finding = _handoff()
    repair = _repair(bundle, finding).model_copy(update={"status": "built"})
    store = Store(bundle, repair)
    started = asyncio.Event()
    release = asyncio.Event()

    class WaitingDiagnosis(Diagnosis):
        async def run(self, bundle, finding, repair):
            started.set()
            await release.wait()
            return await super().run(bundle, finding, repair)

    diagnosis = WaitingDiagnosis(finding)
    workflow = RepairWorkflow(_settings(tmp_path), store, Reader(), diagnosis)

    async def run() -> None:
        task = asyncio.create_task(workflow.verify_fix(bundle.task.correlation, repair.id))
        await started.wait()
        status = await workflow.get_fix_status(bundle.task.correlation, repair.id)
        assert status.status == "retesting"
        assert diagnosis.cleanups == 0
        release.set()
        assert (await task).status == "retested"

    asyncio.run(run())


def test_status_retries_failed_cleanup_without_retest(tmp_path: Path) -> None:
    bundle, finding = _handoff()
    repair = _repair(bundle, finding)
    store = Store(bundle, repair)

    class FlakyCleanup(Diagnosis):
        async def cleanup(self, repair, context):
            self.cleanups += 1
            if self.cleanups == 1:
                raise ValueError("engine unavailable")

    diagnosis = FlakyCleanup(finding)
    workflow = RepairWorkflow(_settings(tmp_path), store, Reader(), diagnosis)
    first = asyncio.run(workflow.get_fix_status(bundle.task.correlation, repair.id))
    assert first.status == "needs_reconcile"
    assert "cleanup failed" in (first.failure_reason or "")
    second = asyncio.run(workflow.get_fix_status(bundle.task.correlation, repair.id))
    assert "cleanup failed" not in (second.failure_reason or "")
    assert diagnosis.cleanups == 2
    assert diagnosis.calls == 0


def test_failed_retest_can_retry_cleanup_without_retesting(tmp_path: Path) -> None:
    bundle, finding = _handoff()
    repair = _repair(bundle, finding).model_copy(update={"status": "built"})
    store = Store(bundle, repair)

    class FailedDiagnosis(Diagnosis):
        async def cleanup(self, repair, context):
            self.cleanups += 1
            if self.cleanups == 1:
                raise ValueError("Docker teardown failed")

    diagnosis = FailedDiagnosis(finding, fail=True)
    workflow = RepairWorkflow(_settings(tmp_path), store, Reader(), diagnosis)
    with pytest.raises(ValueError, match="diagnostic comparison failed"):
        asyncio.run(workflow.verify_fix(bundle.task.correlation, repair.id))
    assert store.repair.status == "failed"
    assert "cleanup failed:" in (store.repair.failure_reason or "")
    result = asyncio.run(workflow.get_fix_status(bundle.task.correlation, repair.id))
    assert result.status == "failed"
    assert "cleanup failed:" not in (result.failure_reason or "")
    assert diagnosis.cleanups == 2
    assert diagnosis.calls == 1


def test_cancelled_diagnosis_retest_requires_reconciliation(tmp_path: Path) -> None:
    bundle, finding = _handoff()
    repair = _repair(bundle, finding).model_copy(update={"status": "built"})
    store = Store(bundle, repair)
    started = asyncio.Event()

    class WaitingDiagnosis:
        async def run(self, bundle, finding, repair):
            started.set()
            await asyncio.Event().wait()

        async def cleanup(self, repair, context):
            pass

    workflow = RepairWorkflow(_settings(tmp_path), store, Reader(), WaitingDiagnosis())

    async def cancel_retest() -> None:
        task = asyncio.create_task(workflow.verify_fix(bundle.task.correlation, repair.id))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_retest())
    assert store.repair.status == "needs_reconcile"
    assert bundle.findings[0] == finding


def test_preparing_left_by_exited_worker_becomes_unknown_without_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, finding = _handoff()
    context = bundle.task.correlation.model_copy(update={"operation_id": "fix-orphan"})
    identity = hashlib.sha256(f"{context.task_id}\n{context.operation_id}".encode()).hexdigest()[
        :24
    ]
    prior = RepairRecord(
        id="repair-" + identity,
        task_id=context.task_id,
        finding_id=finding.id,
        operation_id=context.operation_id,
        attempt_id="worker-that-exited",
        status="preparing",
        source_commit=bundle.task.project.commit,
        patch_sha256=hashlib.sha256(b"test patch").hexdigest(),
        parent_key_column="user_id",
    )
    store = Store(bundle, prior)
    monkeypatch.setattr(
        "project_doctor.workflows.repair.inspect_target",
        lambda *args: pytest.fail("reconciliation inspected changed target source"),
    )
    monkeypatch.setattr(
        store, "load_bundle", lambda task_id: pytest.fail("reconciliation reloaded handoff")
    )
    workflow = RepairWorkflow(_settings(tmp_path), store, Reader(False), Diagnosis(finding))
    with pytest.raises(ValueError, match="operation_conflict"):
        asyncio.run(workflow.submit_fix_patch(context, finding.id, "changed patch"))
    assert store.repair == prior
    result = asyncio.run(workflow.submit_fix_patch(context, finding.id, "test patch"))
    assert result.status == "needs_reconcile"
    assert "exited" in (result.failure_reason or "")
    assert store.repair == result
